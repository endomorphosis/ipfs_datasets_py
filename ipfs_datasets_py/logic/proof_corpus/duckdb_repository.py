"""DuckDB index projection for immutable proof-corpus objects (DQK-028).

Index immutable proof-corpus manifests, envelopes, revocations, and
attestations by **verified CID** while leaving identity-bearing canonical
bytes in content-addressed storage.

Authority model:

* DuckDB (or the in-process index) holds **secondary projection rows** only —
  kind, verified CID/digest, family/profile bindings, revocation and
  contradiction edges.  Identity-bearing canonical bytes never live in the
  index payload columns.
* Content-addressed storage holds the exact put-time bytes; re-get returns
  those same bytes unchanged.  Envelope CIDs and digests are re-verified on
  every put and authoritative get.
* Authoritative hits exclude revoked and contradicted CIDs.
* Tampered objects fail closed: digest/CID drift never loads as a usable hit.

Importing this module is inert: no DuckDB, network, or filesystem I/O.  Unit
tests exercise the pure-Python repository without a server.  An optional
DuckDB connection may install catalog DDL for production projections.
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Any, Final

from .manifest import (
    ProofCorpusManifest,
    ProofCorpusManifestError,
    ProofCorpusManifestIntegrityError,
)
from .model import (
    AttestedProofEnvelope,
    AttestedProofIntegrityError,
    AttestedProofModelError,
)
from .revocation import (
    ProofRevocationError,
    ProofRevocationIntegrityError,
    ProofRevocationSnapshot,
    RevocationEntry,
    cumulative_revoked_cids,
)
from .schemas import (
    ArtifactEnvelope,
    ProofCorpusIntegrityError,
    ProofCorpusSchemaError,
    as_mapping,
    canonical_bytes,
    require_digest,
    require_text,
)

# ---------------------------------------------------------------------------
# Schema / interface pins
# ---------------------------------------------------------------------------

PROOF_CORPUS_DUCKDB_REPOSITORY_INTERFACE: Final = "ProofCorpusDuckDBRepository@1"
PROOF_CORPUS_DUCKDB_REPOSITORY_SCHEMA_VERSION: Final = (
    "proof-corpus-duckdb-repository/v1"
)
CORPUS_CATALOG_NAME: Final = "proof_corpus"

# Catalog tables declared for the corpus projection (index only — no body
# columns holding identity-bearing canonical bytes).
CORPUS_CATALOG_TABLES: Final[tuple[str, ...]] = (
    "corpus_objects",
    "corpus_blob_refs",
    "corpus_revocation_targets",
    "corpus_contradictions",
    "corpus_access_statistics",
)

CORPUS_CATALOG_DDL: Final[str] = """
CREATE TABLE IF NOT EXISTS corpus_objects (
    content_cid VARCHAR PRIMARY KEY,
    content_digest VARCHAR NOT NULL,
    object_kind VARCHAR NOT NULL,
    family VARCHAR NOT NULL,
    profile VARCHAR NOT NULL,
    source_id VARCHAR NOT NULL,
    source_digest VARCHAR NOT NULL,
    subject_cid VARCHAR NOT NULL,
    corpus_root_cid VARCHAR NOT NULL,
    media_type VARCHAR NOT NULL,
    byte_size BIGINT NOT NULL,
    indexed_at DOUBLE NOT NULL,
    metadata_json VARCHAR NOT NULL,
    schema_version VARCHAR NOT NULL
);

CREATE TABLE IF NOT EXISTS corpus_blob_refs (
    content_cid VARCHAR PRIMARY KEY,
    content_digest VARCHAR NOT NULL,
    media_type VARCHAR NOT NULL,
    byte_size BIGINT NOT NULL,
    location_hint VARCHAR NOT NULL
);

CREATE TABLE IF NOT EXISTS corpus_revocation_targets (
    target_cid VARCHAR NOT NULL,
    snapshot_cid VARCHAR NOT NULL,
    reason_kind VARCHAR NOT NULL,
    reason VARCHAR NOT NULL,
    issuer_id VARCHAR NOT NULL,
    revoked_at VARCHAR NOT NULL,
    entry_digest VARCHAR NOT NULL,
    ordinal INTEGER NOT NULL,
    PRIMARY KEY (target_cid, snapshot_cid)
);

CREATE TABLE IF NOT EXISTS corpus_contradictions (
    target_cid VARCHAR NOT NULL,
    contradicting_cid VARCHAR NOT NULL,
    reason VARCHAR NOT NULL,
    recorded_at DOUBLE NOT NULL,
    PRIMARY KEY (target_cid, contradicting_cid)
);

CREATE TABLE IF NOT EXISTS corpus_access_statistics (
    content_cid VARCHAR PRIMARY KEY,
    hits BIGINT NOT NULL,
    misses BIGINT NOT NULL,
    writes BIGINT NOT NULL,
    rejections BIGINT NOT NULL,
    last_access_at DOUBLE NOT NULL
);
""".strip()


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class ProofCorpusDuckDBRepositoryError(ValueError):
    """Raised when a corpus repository operation cannot proceed safely."""


class ProofCorpusDuckDBRepositoryIntegrityError(
    ProofCorpusDuckDBRepositoryError
):
    """Raised when a stored object fails integrity rehash or CID verification."""


class ProofCorpusDuckDBRepositoryAuthorityError(
    ProofCorpusDuckDBRepositoryError
):
    """Raised when authority would be granted to revoked or contradicted evidence."""


# ---------------------------------------------------------------------------
# Closed vocabularies
# ---------------------------------------------------------------------------


class CorpusObjectKind(StrEnum):
    """Closed object kinds projected into the corpus index."""

    ENVELOPE = "envelope"
    ATTESTED_ENVELOPE = "attested_envelope"
    MANIFEST = "manifest"
    REVOCATION = "revocation"
    ATTESTATION = "attestation"


class AuthoritativeHitReason(StrEnum):
    """Closed reasons for authoritative / non-authoritative lookup outcomes."""

    HIT = "hit"
    MISS = "miss"
    REVOKED = "revoked"
    CONTRADICTED = "contradicted"
    TAMPERED = "tampered"
    KIND_MISMATCH = "kind_mismatch"


_MEDIA_TYPE_JSON: Final = "application/json; charset=utf-8"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _sha256_digest(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _require_bytes(value: object, field_name: str) -> bytes:
    if not isinstance(value, (bytes, bytearray)):
        raise ProofCorpusDuckDBRepositoryError(
            f"{field_name} must be bytes"
        )
    return bytes(value)


def _json_ready(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, Mapping):
        return {
            str(key): _json_ready(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, Sequence) and not isinstance(
        value, (str, bytes, bytearray)
    ):
        return [_json_ready(item) for item in value]
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        return _json_ready(to_dict())
    raise ProofCorpusDuckDBRepositoryError(
        f"value of type {type(value).__name__} is not JSON-serializable "
        "for the corpus repository"
    )


def repository_canonical_bytes(value: Any) -> bytes:
    """Canonical JSON bytes used for identity-bearing corpus objects."""

    return json.dumps(
        _json_ready(value),
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def repository_content_digest(value: Any) -> str:
    """Return a ``sha256:<hex>`` digest of repository-canonical JSON."""

    if isinstance(value, (bytes, bytearray)):
        return _sha256_digest(bytes(value))
    return _sha256_digest(repository_canonical_bytes(value))


# ---------------------------------------------------------------------------
# Content-addressed blob store (identity-bearing bytes stay here)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ContentAddressedBlob:
    """One immutable content-addressed blob held outside the index tables."""

    content_cid: str
    content_digest: str
    data: bytes
    media_type: str = _MEDIA_TYPE_JSON
    location_hint: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "content_cid", require_text(self.content_cid, "content_cid")
        )
        object.__setattr__(
            self,
            "content_digest",
            require_digest(self.content_digest, "content_digest"),
        )
        data = _require_bytes(self.data, "data")
        object.__setattr__(self, "data", data)
        object.__setattr__(
            self, "media_type", require_text(self.media_type, "media_type")
        )
        hint = str(self.location_hint or "").strip()
        if hint.startswith(("/", "\\")) or ".." in hint.split("/"):
            raise ProofCorpusDuckDBRepositoryError(
                "location_hint must not be a filesystem path authority"
            )
        object.__setattr__(self, "location_hint", hint)
        recomputed = _sha256_digest(data)
        if recomputed != self.content_digest:
            raise ProofCorpusDuckDBRepositoryIntegrityError(
                "content_digest does not match blob bytes"
            )

    @property
    def byte_size(self) -> int:
        return len(self.data)

    def verify_integrity(self) -> "ContentAddressedBlob":
        recomputed = _sha256_digest(self.data)
        if recomputed != self.content_digest:
            raise ProofCorpusDuckDBRepositoryIntegrityError(
                "stored blob content_digest drifted from bytes"
            )
        return self

    def to_ref_dict(self) -> dict[str, Any]:
        return {
            "byte_size": self.byte_size,
            "content_cid": self.content_cid,
            "content_digest": self.content_digest,
            "location_hint": self.location_hint,
            "media_type": self.media_type,
        }


class ContentAddressedBlobStore:
    """Process-local content-addressed store for identity-bearing bytes.

    Puts are idempotent for identical digests.  Conflicting writes for the
    same CID with different digests fail closed.  Stored bytes are never
    rewritten in place.
    """

    def __init__(self) -> None:
        self._blobs: dict[str, ContentAddressedBlob] = {}
        self._lock = threading.RLock()

    def put(
        self,
        *,
        content_cid: str,
        content_digest: str,
        data: bytes,
        media_type: str = _MEDIA_TYPE_JSON,
        location_hint: str = "",
    ) -> ContentAddressedBlob:
        blob = ContentAddressedBlob(
            content_cid=content_cid,
            content_digest=content_digest,
            data=data,
            media_type=media_type,
            location_hint=location_hint,
        )
        with self._lock:
            existing = self._blobs.get(blob.content_cid)
            if existing is not None:
                if (
                    existing.content_digest != blob.content_digest
                    or existing.data != blob.data
                ):
                    raise ProofCorpusDuckDBRepositoryIntegrityError(
                        f"CID {blob.content_cid!r} already bound to different "
                        "canonical bytes (immutable CA conflict)"
                    )
                # Identical put is idempotent; return the original object so
                # identity of stored bytes is preserved.
                return existing
            # Store an exact copy so callers cannot mutate via shared buffers.
            sealed = ContentAddressedBlob(
                content_cid=blob.content_cid,
                content_digest=blob.content_digest,
                data=bytes(blob.data),
                media_type=blob.media_type,
                location_hint=blob.location_hint,
            )
            self._blobs[sealed.content_cid] = sealed
            return sealed

    def get(self, content_cid: str) -> ContentAddressedBlob | None:
        cid = require_text(content_cid, "content_cid")
        with self._lock:
            blob = self._blobs.get(cid)
            if blob is None:
                return None
            return blob.verify_integrity()

    def get_bytes(self, content_cid: str) -> bytes | None:
        blob = self.get(content_cid)
        if blob is None:
            return None
        # Return a copy so callers cannot mutate the store.
        return bytes(blob.data)

    def contains(self, content_cid: str) -> bool:
        cid = require_text(content_cid, "content_cid")
        with self._lock:
            return cid in self._blobs

    def cids(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(sorted(self._blobs))

    def size(self) -> int:
        with self._lock:
            return len(self._blobs)

    def clear(self) -> None:
        with self._lock:
            self._blobs.clear()


# ---------------------------------------------------------------------------
# Index records (no identity-bearing body bytes)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CorpusIndexRecord:
    """Secondary index row for one verified corpus object.

    Identity-bearing canonical bytes are **not** stored here; only the
    verified CID/digest pointer and projection metadata.
    """

    content_cid: str
    content_digest: str
    object_kind: CorpusObjectKind | str
    family: str = ""
    profile: str = ""
    source_id: str = ""
    source_digest: str = ""
    subject_cid: str = ""
    corpus_root_cid: str = ""
    media_type: str = _MEDIA_TYPE_JSON
    byte_size: int = 0
    indexed_at: float = 0.0
    metadata: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = PROOF_CORPUS_DUCKDB_REPOSITORY_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "content_cid", require_text(self.content_cid, "content_cid")
        )
        object.__setattr__(
            self,
            "content_digest",
            require_digest(self.content_digest, "content_digest"),
        )
        kind = self.object_kind
        if not isinstance(kind, CorpusObjectKind):
            try:
                kind = CorpusObjectKind(str(kind))
            except ValueError as exc:
                allowed = ", ".join(item.value for item in CorpusObjectKind)
                raise ProofCorpusDuckDBRepositoryError(
                    f"object_kind must be one of: {allowed}"
                ) from exc
        object.__setattr__(self, "object_kind", kind)
        object.__setattr__(
            self, "family", str(self.family or "").strip()
        )
        object.__setattr__(
            self, "profile", str(self.profile or "").strip()
        )
        object.__setattr__(
            self, "source_id", str(self.source_id or "").strip()
        )
        source_digest = str(self.source_digest or "").strip()
        if source_digest:
            source_digest = require_digest(source_digest, "source_digest")
        object.__setattr__(self, "source_digest", source_digest)
        object.__setattr__(
            self, "subject_cid", str(self.subject_cid or "").strip()
        )
        object.__setattr__(
            self, "corpus_root_cid", str(self.corpus_root_cid or "").strip()
        )
        object.__setattr__(
            self, "media_type", require_text(self.media_type, "media_type")
        )
        if not isinstance(self.byte_size, int) or isinstance(
            self.byte_size, bool
        ):
            raise ProofCorpusDuckDBRepositoryError("byte_size must be an integer")
        if self.byte_size < 0:
            raise ProofCorpusDuckDBRepositoryError(
                "byte_size must be non-negative"
            )
        if not isinstance(self.indexed_at, (int, float)) or (
            self.indexed_at != self.indexed_at
        ):
            raise ProofCorpusDuckDBRepositoryError(
                "indexed_at must be a finite number"
            )
        object.__setattr__(self, "indexed_at", float(self.indexed_at))
        metadata = dict(as_mapping(self.metadata or {}, "metadata"))
        object.__setattr__(self, "metadata", MappingProxyType(metadata))
        object.__setattr__(
            self,
            "schema_version",
            require_text(self.schema_version, "schema_version"),
        )
        if self.schema_version != PROOF_CORPUS_DUCKDB_REPOSITORY_SCHEMA_VERSION:
            raise ProofCorpusDuckDBRepositoryError(
                f"unsupported repository schema: {self.schema_version!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        kind = (
            self.object_kind.value
            if isinstance(self.object_kind, CorpusObjectKind)
            else str(self.object_kind)
        )
        return {
            "byte_size": self.byte_size,
            "content_cid": self.content_cid,
            "content_digest": self.content_digest,
            "corpus_root_cid": self.corpus_root_cid,
            "family": self.family,
            "indexed_at": self.indexed_at,
            "media_type": self.media_type,
            "metadata": dict(self.metadata),
            "object_kind": kind,
            "profile": self.profile,
            "schema_version": self.schema_version,
            "source_digest": self.source_digest,
            "source_id": self.source_id,
            "subject_cid": self.subject_cid,
        }


@dataclass(frozen=True, slots=True)
class AuthoritativeHit:
    """Result of an authoritative corpus lookup by verified CID."""

    content_cid: str
    hit: bool
    authoritative: bool
    reason: AuthoritativeHitReason | str
    object_kind: CorpusObjectKind | str | None = None
    content_digest: str = ""
    record: CorpusIndexRecord | None = None
    schema_version: str = PROOF_CORPUS_DUCKDB_REPOSITORY_SCHEMA_VERSION
    interface: str = PROOF_CORPUS_DUCKDB_REPOSITORY_INTERFACE

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "content_cid", require_text(self.content_cid, "content_cid")
        )
        if not isinstance(self.hit, bool):
            raise ProofCorpusDuckDBRepositoryError("hit must be a bool")
        if not isinstance(self.authoritative, bool):
            raise ProofCorpusDuckDBRepositoryError(
                "authoritative must be a bool"
            )
        reason = self.reason
        if not isinstance(reason, AuthoritativeHitReason):
            try:
                reason = AuthoritativeHitReason(str(reason))
            except ValueError as exc:
                allowed = ", ".join(item.value for item in AuthoritativeHitReason)
                raise ProofCorpusDuckDBRepositoryError(
                    f"reason must be one of: {allowed}"
                ) from exc
        object.__setattr__(self, "reason", reason)
        if self.object_kind is not None and not isinstance(
            self.object_kind, CorpusObjectKind
        ):
            try:
                object.__setattr__(
                    self, "object_kind", CorpusObjectKind(str(self.object_kind))
                )
            except ValueError as exc:
                raise ProofCorpusDuckDBRepositoryError(
                    f"unknown object_kind: {self.object_kind!r}"
                ) from exc
        if self.authoritative and not self.hit:
            raise ProofCorpusDuckDBRepositoryError(
                "authoritative hits must also be hits"
            )
        if self.authoritative and reason is not AuthoritativeHitReason.HIT:
            raise ProofCorpusDuckDBRepositoryError(
                "authoritative hits must report reason=hit"
            )

    def to_dict(self) -> dict[str, Any]:
        kind = self.object_kind
        if isinstance(kind, CorpusObjectKind):
            kind_value: str | None = kind.value
        elif kind is None:
            kind_value = None
        else:
            kind_value = str(kind)
        reason = (
            self.reason.value
            if isinstance(self.reason, AuthoritativeHitReason)
            else str(self.reason)
        )
        return {
            "authoritative": self.authoritative,
            "content_cid": self.content_cid,
            "content_digest": self.content_digest,
            "hit": self.hit,
            "interface": self.interface,
            "object_kind": kind_value,
            "reason": reason,
            "record": None if self.record is None else self.record.to_dict(),
            "schema_version": self.schema_version,
        }


# ---------------------------------------------------------------------------
# Object materialisation helpers
# ---------------------------------------------------------------------------


def _envelope_canonical_bytes(envelope: ArtifactEnvelope) -> bytes:
    """Identity-bearing envelope bytes (stable across put/get)."""

    verified = envelope.verify_integrity()
    # Use the schema's canonical encoder so bytes match envelope identity.
    return canonical_bytes(verified.to_dict())


def _attested_envelope_canonical_bytes(envelope: AttestedProofEnvelope) -> bytes:
    return repository_canonical_bytes(envelope.to_dict())


def _manifest_canonical_bytes(manifest: ProofCorpusManifest) -> bytes:
    return repository_canonical_bytes(manifest.to_dict())


def _revocation_canonical_bytes(snapshot: ProofRevocationSnapshot) -> bytes:
    return repository_canonical_bytes(snapshot.to_dict())


def _attestation_canonical_bytes(payload: Mapping[str, Any]) -> bytes:
    return repository_canonical_bytes(dict(as_mapping(payload, "attestation")))


def _cid_from_digest(digest: str) -> str:
    from ..ir_core.identity import cid_v1_from_digest

    hex_part = require_digest(digest, "content_digest").removeprefix("sha256:")
    return cid_v1_from_digest(bytes.fromhex(hex_part))


# ---------------------------------------------------------------------------
# Repository
# ---------------------------------------------------------------------------


class ProofCorpusDuckDBRepository:
    """Index proof-corpus objects by verified CID with CA body storage.

    The default construction is process-local and does not require DuckDB.
    Pass ``connection`` to install and (optionally) mirror index rows into a
    DuckDB-like connection.  Identity-bearing bytes always remain in the
    content-addressed blob store.
    """

    def __init__(
        self,
        *,
        connection: Any | None = None,
        blob_store: ContentAddressedBlobStore | None = None,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self._connection = connection
        self._blobs = blob_store or ContentAddressedBlobStore()
        self._clock = clock or time.time
        self._lock = threading.RLock()
        # content_cid -> index record
        self._index: dict[str, CorpusIndexRecord] = {}
        # target_cid -> set of snapshot_cids that revoke it
        self._revocations: dict[str, set[str]] = {}
        # target_cid -> set of contradicting_cids
        self._contradictions: dict[str, set[str]] = {}
        # snapshot_cid -> frozenset of target_cids (for inspection)
        self._revocation_snapshots: dict[str, frozenset[str]] = {}
        self._access: dict[str, dict[str, float | int]] = {}
        self._stats = {
            "hits": 0,
            "misses": 0,
            "writes": 0,
            "rejections": 0,
            "tamper_rejections": 0,
            "revocation_exclusions": 0,
            "contradiction_exclusions": 0,
        }
        if connection is not None:
            self.install_schema(connection)

    # -- identity ------------------------------------------------------------

    @property
    def interface(self) -> str:
        return PROOF_CORPUS_DUCKDB_REPOSITORY_INTERFACE

    @property
    def schema_version(self) -> str:
        return PROOF_CORPUS_DUCKDB_REPOSITORY_SCHEMA_VERSION

    @property
    def blob_store(self) -> ContentAddressedBlobStore:
        return self._blobs

    @staticmethod
    def install_schema(connection: Any) -> None:
        """Apply corpus catalog DDL on a DuckDB-like connection."""

        if connection is None:
            raise ProofCorpusDuckDBRepositoryError(
                "connection is required to install schema"
            )
        for statement in CORPUS_CATALOG_DDL.split(";"):
            body = statement.strip()
            if body:
                connection.execute(body)

    def catalog_tables(self) -> tuple[str, ...]:
        return CORPUS_CATALOG_TABLES

    def stats(self) -> dict[str, int]:
        with self._lock:
            return {
                **self._stats,
                "size": len(self._index),
                "blobs": self._blobs.size(),
                "revoked_targets": len(self._revocations),
                "contradicted_targets": len(self._contradictions),
            }

    # -- access tracking -----------------------------------------------------

    def _access_touch(
        self,
        content_cid: str,
        *,
        hit: bool = False,
        miss: bool = False,
        write: bool = False,
        rejection: bool = False,
        now: float,
    ) -> None:
        bucket = self._access.setdefault(
            content_cid,
            {
                "hits": 0,
                "misses": 0,
                "writes": 0,
                "rejections": 0,
                "last_access_at": 0.0,
            },
        )
        if hit:
            bucket["hits"] = int(bucket["hits"]) + 1
        if miss:
            bucket["misses"] = int(bucket["misses"]) + 1
        if write:
            bucket["writes"] = int(bucket["writes"]) + 1
        if rejection:
            bucket["rejections"] = int(bucket["rejections"]) + 1
        bucket["last_access_at"] = float(now)

    # -- revocation / contradiction predicates -------------------------------

    def is_revoked(self, content_cid: str) -> bool:
        cid = require_text(content_cid, "content_cid")
        with self._lock:
            return cid in self._revocations and bool(self._revocations[cid])

    def is_contradicted(self, content_cid: str) -> bool:
        cid = require_text(content_cid, "content_cid")
        with self._lock:
            return cid in self._contradictions and bool(
                self._contradictions[cid]
            )

    def revoked_cids(self) -> frozenset[str]:
        with self._lock:
            return frozenset(
                cid for cid, snaps in self._revocations.items() if snaps
            )

    def contradicted_cids(self) -> frozenset[str]:
        with self._lock:
            return frozenset(
                cid for cid, peers in self._contradictions.items() if peers
            )

    def is_authoritative_candidate(self, content_cid: str) -> bool:
        """Return True when *content_cid* is neither revoked nor contradicted."""

        return not self.is_revoked(content_cid) and not self.is_contradicted(
            content_cid
        )

    # -- internal put path ---------------------------------------------------

    def _mirror_index_row(
        self, record: CorpusIndexRecord, blob: ContentAddressedBlob
    ) -> None:
        """Best-effort projection into an injected DuckDB connection."""

        connection = self._connection
        if connection is None:
            return
        try:
            connection.execute(
                """
                INSERT OR REPLACE INTO corpus_objects (
                    content_cid, content_digest, object_kind, family, profile,
                    source_id, source_digest, subject_cid, corpus_root_cid,
                    media_type, byte_size, indexed_at, metadata_json,
                    schema_version
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    record.content_cid,
                    record.content_digest,
                    record.object_kind.value
                    if isinstance(record.object_kind, CorpusObjectKind)
                    else str(record.object_kind),
                    record.family,
                    record.profile,
                    record.source_id,
                    record.source_digest,
                    record.subject_cid,
                    record.corpus_root_cid,
                    record.media_type,
                    record.byte_size,
                    record.indexed_at,
                    json.dumps(
                        dict(record.metadata),
                        ensure_ascii=False,
                        separators=(",", ":"),
                        sort_keys=True,
                    ),
                    record.schema_version,
                ],
            )
            connection.execute(
                """
                INSERT OR REPLACE INTO corpus_blob_refs (
                    content_cid, content_digest, media_type, byte_size,
                    location_hint
                ) VALUES (?, ?, ?, ?, ?)
                """,
                [
                    blob.content_cid,
                    blob.content_digest,
                    blob.media_type,
                    blob.byte_size,
                    blob.location_hint,
                ],
            )
        except Exception as exc:  # pragma: no cover - connection-specific
            raise ProofCorpusDuckDBRepositoryError(
                f"failed to mirror corpus index row into DuckDB: {exc}"
            ) from exc

    # -- public put APIs -----------------------------------------------------

    def put_envelope(
        self,
        envelope: ArtifactEnvelope | Mapping[str, Any],
        *,
        location_hint: str = "",
    ) -> CorpusIndexRecord:
        """Index a verified :class:`ArtifactEnvelope` by its content CID.

        Canonical envelope bytes and the envelope's content CID are preserved
        exactly; the index stores only projection metadata.
        """

        try:
            if isinstance(envelope, ArtifactEnvelope):
                env = envelope.verify_integrity()
            else:
                env = ArtifactEnvelope.from_dict(
                    as_mapping(envelope, "artifact envelope")
                )
        except (ProofCorpusSchemaError, ProofCorpusIntegrityError) as exc:
            raise ProofCorpusDuckDBRepositoryIntegrityError(
                f"envelope failed integrity verification: {exc}"
            ) from exc
        data = _envelope_canonical_bytes(env)
        # Authority identity is the envelope content_digest (identity payload).
        # Stored bytes are the full to_dict() form; both are retained, neither
        # is rewritten.
        stored_digest = _sha256_digest(data)
        return self._put_object_with_object_cid(
            data=data,
            object_cid=env.content_cid,
            object_digest=env.content_digest,
            stored_digest=stored_digest,
            object_kind=CorpusObjectKind.ENVELOPE,
            family=env.family.value,
            profile=env.profile,
            source_id=env.source_id,
            source_digest=env.source_digest,
            media_type=_MEDIA_TYPE_JSON,
            metadata={
                "artifact_cid": env.artifact_cid,
                "artifact_digest": env.artifact_digest,
                "envelope_schema_version": env.schema_version,
                "producer_id": env.producer_id,
                "review_state": env.review_state,
                "stored_byte_digest": stored_digest,
            },
            location_hint=location_hint,
        )

    def put_attested_envelope(
        self,
        envelope: AttestedProofEnvelope | Mapping[str, Any],
        *,
        location_hint: str = "",
    ) -> CorpusIndexRecord:
        """Index a verified :class:`AttestedProofEnvelope` by its content CID."""

        try:
            if isinstance(envelope, AttestedProofEnvelope):
                env = envelope
                # Rehash via to_dict round-trip identity (constructor already did).
                if not env.content_cid or not env.content_digest:
                    raise AttestedProofIntegrityError(
                        "attested envelope missing content identity"
                    )
            else:
                env = AttestedProofEnvelope.from_dict(
                    as_mapping(envelope, "attested proof envelope")
                )
        except (
            AttestedProofModelError,
            AttestedProofIntegrityError,
            ProofCorpusSchemaError,
        ) as exc:
            raise ProofCorpusDuckDBRepositoryIntegrityError(
                f"attested envelope failed integrity verification: {exc}"
            ) from exc
        data = _attested_envelope_canonical_bytes(env)
        stored_digest = _sha256_digest(data)
        family = (
            env.family.value
            if hasattr(env.family, "value")
            else str(env.family)
        )
        return self._put_object_with_object_cid(
            data=data,
            object_cid=env.content_cid,
            object_digest=env.content_digest,
            stored_digest=stored_digest,
            object_kind=CorpusObjectKind.ATTESTED_ENVELOPE,
            family=family,
            profile=str(getattr(env, "security_profile", "") or ""),
            corpus_root_cid=str(env.corpus_root_cid or ""),
            media_type=_MEDIA_TYPE_JSON,
            metadata={
                "attestation_kind": (
                    env.attestation_kind.value
                    if hasattr(env.attestation_kind, "value")
                    else str(env.attestation_kind)
                ),
                "envelope_schema_version": env.schema_version,
                "interface": env.interface,
                "obligation_digest": env.obligation_digest,
                "result_authority": (
                    env.result_authority.value
                    if hasattr(env.result_authority, "value")
                    else str(env.result_authority)
                ),
                "stored_byte_digest": stored_digest,
            },
            location_hint=location_hint,
        )

    def put_manifest(
        self,
        manifest: ProofCorpusManifest | Mapping[str, Any],
        *,
        location_hint: str = "",
    ) -> CorpusIndexRecord:
        """Index a verified :class:`ProofCorpusManifest` by its content CID."""

        try:
            if isinstance(manifest, ProofCorpusManifest):
                man = manifest
            else:
                man = ProofCorpusManifest.from_dict(
                    as_mapping(manifest, "proof corpus manifest")
                )
        except (
            ProofCorpusManifestError,
            ProofCorpusManifestIntegrityError,
        ) as exc:
            raise ProofCorpusDuckDBRepositoryIntegrityError(
                f"manifest failed integrity verification: {exc}"
            ) from exc
        data = _manifest_canonical_bytes(man)
        stored_digest = _sha256_digest(data)
        return self._put_object_with_object_cid(
            data=data,
            object_cid=man.content_cid,
            object_digest=man.content_digest,
            stored_digest=stored_digest,
            object_kind=CorpusObjectKind.MANIFEST,
            family=str(man.domain or ""),
            corpus_root_cid=str(man.root_cid or man.content_cid),
            media_type=_MEDIA_TYPE_JSON,
            metadata={
                "generation": man.generation,
                "interface": man.interface,
                "manifest_schema_version": man.schema_version,
                "namespace": man.namespace,
                "producer_id": man.producer_id,
                "revocation_root_cid": man.revocation_root_cid,
                "root_cid": man.root_cid,
                "stored_byte_digest": stored_digest,
            },
            location_hint=location_hint,
        )

    def put_revocation(
        self,
        snapshot: ProofRevocationSnapshot | Mapping[str, Any],
        *,
        location_hint: str = "",
        apply_targets: bool = True,
    ) -> CorpusIndexRecord:
        """Index a verified revocation snapshot and optionally apply targets.

        When *apply_targets* is True (default), every entry target CID is
        marked revoked so subsequent authoritative lookups exclude them.
        """

        try:
            if isinstance(snapshot, ProofRevocationSnapshot):
                snap = snapshot
            else:
                snap = ProofRevocationSnapshot.from_dict(
                    as_mapping(snapshot, "revocation snapshot")
                )
        except (ProofRevocationError, ProofRevocationIntegrityError) as exc:
            raise ProofCorpusDuckDBRepositoryIntegrityError(
                f"revocation snapshot failed integrity verification: {exc}"
            ) from exc
        data = _revocation_canonical_bytes(snap)
        stored_digest = _sha256_digest(data)
        record = self._put_object_with_object_cid(
            data=data,
            object_cid=snap.content_cid,
            object_digest=snap.content_digest,
            stored_digest=stored_digest,
            object_kind=CorpusObjectKind.REVOCATION,
            corpus_root_cid=str(snap.corpus_root_cid or ""),
            media_type=_MEDIA_TYPE_JSON,
            metadata={
                "entry_count": len(snap.entries),
                "generation": snap.generation,
                "interface": snap.interface,
                "parent_cid": snap.parent_cid,
                "producer_id": snap.producer_id,
                "root_cid": snap.root_cid,
                "snapshot_schema_version": snap.schema_version,
                "stored_byte_digest": stored_digest,
            },
            location_hint=location_hint,
        )
        if apply_targets:
            self._apply_revocation_snapshot(snap)
        return record

    def put_attestation(
        self,
        attestation: Mapping[str, Any],
        *,
        subject_cid: str,
        content_cid: str | None = None,
        content_digest: str | None = None,
        location_hint: str = "",
        family: str = "",
        profile: str = "",
    ) -> CorpusIndexRecord:
        """Index an attestation payload bound to a subject envelope CID.

        Attestation identity is content-addressed over the canonical payload.
        The subject envelope CID is projected for join queries; it is not
        rewritten into the payload.
        """

        payload = dict(as_mapping(attestation, "attestation"))
        subject = require_text(subject_cid, "subject_cid")
        data = _attestation_canonical_bytes(payload)
        stored_digest = _sha256_digest(data)
        if content_digest is not None:
            claimed = require_digest(content_digest, "content_digest")
            if claimed != stored_digest:
                raise ProofCorpusDuckDBRepositoryIntegrityError(
                    "attestation content_digest does not match payload bytes"
                )
        object_digest = stored_digest
        if content_cid is not None:
            object_cid = require_text(content_cid, "content_cid")
            # When a caller supplies a CID it must match digest-derived CIDv1.
            derived = _cid_from_digest(object_digest)
            if object_cid != derived:
                raise ProofCorpusDuckDBRepositoryIntegrityError(
                    "attestation content_cid does not match payload digest"
                )
        else:
            object_cid = _cid_from_digest(object_digest)
        return self._put_object_with_object_cid(
            data=data,
            object_cid=object_cid,
            object_digest=object_digest,
            stored_digest=stored_digest,
            object_kind=CorpusObjectKind.ATTESTATION,
            family=family,
            profile=profile,
            subject_cid=subject,
            media_type=_MEDIA_TYPE_JSON,
            metadata={
                "stored_byte_digest": stored_digest,
                "subject_cid": subject,
            },
            location_hint=location_hint,
        )

    def _put_object_with_object_cid(
        self,
        *,
        data: bytes,
        object_cid: str,
        object_digest: str,
        stored_digest: str,
        object_kind: CorpusObjectKind,
        family: str = "",
        profile: str = "",
        source_id: str = "",
        source_digest: str = "",
        subject_cid: str = "",
        corpus_root_cid: str = "",
        media_type: str = _MEDIA_TYPE_JSON,
        metadata: Mapping[str, Any] | None = None,
        location_hint: str = "",
    ) -> CorpusIndexRecord:
        """Store exact *data* under *object_cid* without rewriting either.

        *object_digest* is the object's authority identity digest (projected
        into the index).  *stored_digest* is the digest of the exact put-time
        bytes held in content-addressed storage.  For many corpus objects these
        differ because the authority digest is over an identity payload that
        excludes the content_cid field, while stored bytes are the full
        ``to_dict()`` form.  Both are retained; neither is rewritten.
        """

        data = _require_bytes(data, "data")
        object_cid = require_text(object_cid, "content_cid")
        object_digest = require_digest(object_digest, "content_digest")
        stored_digest = require_digest(stored_digest, "stored_digest")
        if _sha256_digest(data) != stored_digest:
            raise ProofCorpusDuckDBRepositoryIntegrityError(
                "stored_digest does not match put-time bytes"
            )
        now = float(self._clock())
        # CA store keys by object CID with the digest of the exact bytes so
        # tamper detection on the wire form is fail-closed.
        blob = self._blobs.put(
            content_cid=object_cid,
            content_digest=stored_digest,
            data=data,
            media_type=media_type,
            location_hint=location_hint,
        )
        meta = dict(metadata or {})
        meta.setdefault("object_digest", object_digest)
        meta.setdefault("stored_byte_digest", stored_digest)
        record = CorpusIndexRecord(
            content_cid=object_cid,
            content_digest=object_digest,
            object_kind=object_kind,
            family=family,
            profile=profile,
            source_id=source_id,
            source_digest=source_digest,
            subject_cid=subject_cid,
            corpus_root_cid=corpus_root_cid,
            media_type=media_type,
            byte_size=blob.byte_size,
            indexed_at=now,
            metadata=meta,
        )
        with self._lock:
            existing = self._index.get(object_cid)
            if existing is not None:
                if (
                    existing.content_digest != record.content_digest
                    or existing.object_kind != record.object_kind
                    or existing.byte_size != record.byte_size
                ):
                    self._stats["rejections"] += 1
                    self._access_touch(object_cid, rejection=True, now=now)
                    raise ProofCorpusDuckDBRepositoryIntegrityError(
                        f"CID {object_cid!r} is already indexed under a "
                        "different identity"
                    )
                existing_blob = self._blobs.get(object_cid)
                if existing_blob is None or existing_blob.data != data:
                    self._stats["rejections"] += 1
                    self._stats["tamper_rejections"] += 1
                    self._access_touch(object_cid, rejection=True, now=now)
                    raise ProofCorpusDuckDBRepositoryIntegrityError(
                        f"CID {object_cid!r} re-put with different bytes"
                    )
                self._access_touch(object_cid, write=True, now=now)
                self._stats["writes"] += 1
                return existing
            self._index[object_cid] = record
            self._stats["writes"] += 1
            self._access_touch(object_cid, write=True, now=now)
            self._mirror_index_row(record, blob)
            return record

    def _apply_revocation_snapshot(
        self, snapshot: ProofRevocationSnapshot
    ) -> None:
        snapshot_cid = require_text(snapshot.content_cid, "content_cid")
        targets = frozenset(
            require_text(entry.target_cid, "target_cid")
            for entry in snapshot.entries
        )
        now = float(self._clock())
        with self._lock:
            self._revocation_snapshots[snapshot_cid] = targets
            for entry in snapshot.entries:
                target = entry.target_cid
                self._revocations.setdefault(target, set()).add(snapshot_cid)
                self._mirror_revocation_entry(snapshot_cid, entry)
            # Also apply cumulative helper for lineage-aware consumers.
            cumulative = cumulative_revoked_cids((snapshot,))
            for target in cumulative:
                self._revocations.setdefault(target, set()).add(snapshot_cid)
            _ = now  # reserved for future access accounting on apply

    def _mirror_revocation_entry(
        self, snapshot_cid: str, entry: RevocationEntry
    ) -> None:
        connection = self._connection
        if connection is None:
            return
        try:
            kind = (
                entry.reason_kind.value
                if hasattr(entry.reason_kind, "value")
                else str(entry.reason_kind)
            )
            connection.execute(
                """
                INSERT OR REPLACE INTO corpus_revocation_targets (
                    target_cid, snapshot_cid, reason_kind, reason,
                    issuer_id, revoked_at, entry_digest, ordinal
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    entry.target_cid,
                    snapshot_cid,
                    kind,
                    entry.reason,
                    entry.issuer_id,
                    entry.revoked_at,
                    entry.entry_digest,
                    entry.ordinal,
                ],
            )
        except Exception as exc:  # pragma: no cover
            raise ProofCorpusDuckDBRepositoryError(
                f"failed to mirror revocation entry into DuckDB: {exc}"
            ) from exc

    def record_contradiction(
        self,
        target_cid: str,
        contradicting_cid: str,
        *,
        reason: str = "contradicted",
    ) -> None:
        """Mark *target_cid* as contradicted by *contradicting_cid*.

        Contradicted evidence is excluded from authoritative hits.  The
        underlying CA bytes remain available for audit via non-authoritative
        getters.
        """

        target = require_text(target_cid, "target_cid")
        peer = require_text(contradicting_cid, "contradicting_cid")
        reason_text = require_text(reason, "reason")
        if target == peer:
            raise ProofCorpusDuckDBRepositoryError(
                "a CID cannot contradict itself"
            )
        now = float(self._clock())
        with self._lock:
            self._contradictions.setdefault(target, set()).add(peer)
            connection = self._connection
            if connection is not None:
                try:
                    connection.execute(
                        """
                        INSERT OR REPLACE INTO corpus_contradictions (
                            target_cid, contradicting_cid, reason, recorded_at
                        ) VALUES (?, ?, ?, ?)
                        """,
                        [target, peer, reason_text, now],
                    )
                except Exception as exc:  # pragma: no cover
                    raise ProofCorpusDuckDBRepositoryError(
                        f"failed to mirror contradiction into DuckDB: {exc}"
                    ) from exc

    # -- get / lookup APIs ---------------------------------------------------

    def get_bytes(self, content_cid: str) -> bytes:
        """Return exact content-addressed bytes for *content_cid*.

        Fails closed if the CID is unknown or the stored blob fails integrity.
        """

        cid = require_text(content_cid, "content_cid")
        now = float(self._clock())
        try:
            data = self._blobs.get_bytes(cid)
        except ProofCorpusDuckDBRepositoryIntegrityError:
            with self._lock:
                self._stats["tamper_rejections"] += 1
                self._stats["rejections"] += 1
                self._access_touch(cid, rejection=True, now=now)
            raise
        if data is None:
            with self._lock:
                self._stats["misses"] += 1
                self._access_touch(cid, miss=True, now=now)
            raise ProofCorpusDuckDBRepositoryError(
                f"no content-addressed bytes for CID {cid!r}"
            )
        with self._lock:
            self._stats["hits"] += 1
            self._access_touch(cid, hit=True, now=now)
        return data

    def get_index_record(self, content_cid: str) -> CorpusIndexRecord | None:
        cid = require_text(content_cid, "content_cid")
        with self._lock:
            return self._index.get(cid)

    def lookup(
        self,
        content_cid: str,
        *,
        authoritative_only: bool = True,
        expected_kind: CorpusObjectKind | str | None = None,
    ) -> AuthoritativeHit:
        """Lookup an object by verified CID with authority filtering.

        When *authoritative_only* is True (default), revoked or contradicted
        CIDs are not returned as authoritative hits.  Tampered blobs fail
        closed (reason ``tampered``, never an authoritative hit).
        """

        cid = require_text(content_cid, "content_cid")
        now = float(self._clock())
        expected: CorpusObjectKind | None = None
        if expected_kind is not None:
            if isinstance(expected_kind, CorpusObjectKind):
                expected = expected_kind
            else:
                try:
                    expected = CorpusObjectKind(str(expected_kind))
                except ValueError as exc:
                    raise ProofCorpusDuckDBRepositoryError(
                        f"unknown expected_kind: {expected_kind!r}"
                    ) from exc

        with self._lock:
            record = self._index.get(cid)
            if record is None:
                self._stats["misses"] += 1
                self._access_touch(cid, miss=True, now=now)
                return AuthoritativeHit(
                    content_cid=cid,
                    hit=False,
                    authoritative=False,
                    reason=AuthoritativeHitReason.MISS,
                )

            # Integrity of CA bytes — fail closed on tamper.
            try:
                blob = self._blobs.get(cid)
            except ProofCorpusDuckDBRepositoryIntegrityError:
                self._stats["tamper_rejections"] += 1
                self._stats["rejections"] += 1
                self._access_touch(cid, rejection=True, now=now)
                return AuthoritativeHit(
                    content_cid=cid,
                    hit=False,
                    authoritative=False,
                    reason=AuthoritativeHitReason.TAMPERED,
                    object_kind=record.object_kind,
                    content_digest=record.content_digest,
                    record=record,
                )
            if blob is None:
                self._stats["tamper_rejections"] += 1
                self._stats["rejections"] += 1
                self._access_touch(cid, rejection=True, now=now)
                return AuthoritativeHit(
                    content_cid=cid,
                    hit=False,
                    authoritative=False,
                    reason=AuthoritativeHitReason.TAMPERED,
                    object_kind=record.object_kind,
                    content_digest=record.content_digest,
                    record=record,
                )
            stored_digest = str(
                record.metadata.get("stored_byte_digest") or blob.content_digest
            )
            if _sha256_digest(blob.data) != stored_digest:
                self._stats["tamper_rejections"] += 1
                self._stats["rejections"] += 1
                self._access_touch(cid, rejection=True, now=now)
                return AuthoritativeHit(
                    content_cid=cid,
                    hit=False,
                    authoritative=False,
                    reason=AuthoritativeHitReason.TAMPERED,
                    object_kind=record.object_kind,
                    content_digest=record.content_digest,
                    record=record,
                )

            if expected is not None and record.object_kind is not expected:
                self._stats["rejections"] += 1
                self._access_touch(cid, rejection=True, now=now)
                return AuthoritativeHit(
                    content_cid=cid,
                    hit=True,
                    authoritative=False,
                    reason=AuthoritativeHitReason.KIND_MISMATCH,
                    object_kind=record.object_kind,
                    content_digest=record.content_digest,
                    record=record,
                )

            if self.is_revoked(cid):
                self._stats["revocation_exclusions"] += 1
                self._stats["hits"] += 1
                self._access_touch(cid, hit=True, now=now)
                return AuthoritativeHit(
                    content_cid=cid,
                    hit=True,
                    authoritative=False,
                    reason=AuthoritativeHitReason.REVOKED,
                    object_kind=record.object_kind,
                    content_digest=record.content_digest,
                    record=record,
                )

            if self.is_contradicted(cid):
                self._stats["contradiction_exclusions"] += 1
                self._stats["hits"] += 1
                self._access_touch(cid, hit=True, now=now)
                return AuthoritativeHit(
                    content_cid=cid,
                    hit=True,
                    authoritative=False,
                    reason=AuthoritativeHitReason.CONTRADICTED,
                    object_kind=record.object_kind,
                    content_digest=record.content_digest,
                    record=record,
                )

            if not authoritative_only:
                self._stats["hits"] += 1
                self._access_touch(cid, hit=True, now=now)
                return AuthoritativeHit(
                    content_cid=cid,
                    hit=True,
                    authoritative=True,
                    reason=AuthoritativeHitReason.HIT,
                    object_kind=record.object_kind,
                    content_digest=record.content_digest,
                    record=record,
                )

            self._stats["hits"] += 1
            self._access_touch(cid, hit=True, now=now)
            return AuthoritativeHit(
                content_cid=cid,
                hit=True,
                authoritative=True,
                reason=AuthoritativeHitReason.HIT,
                object_kind=record.object_kind,
                content_digest=record.content_digest,
                record=record,
            )

    def get_authoritative(
        self,
        content_cid: str,
        *,
        expected_kind: CorpusObjectKind | str | None = None,
    ) -> AuthoritativeHit:
        """Return an authoritative hit or a structured non-authoritative result."""

        return self.lookup(
            content_cid,
            authoritative_only=True,
            expected_kind=expected_kind,
        )

    def list_authoritative_cids(
        self,
        *,
        object_kind: CorpusObjectKind | str | None = None,
        family: str | None = None,
        profile: str | None = None,
    ) -> tuple[str, ...]:
        """Return sorted CIDs that currently pass the authority filter."""

        kind_filter: CorpusObjectKind | None = None
        if object_kind is not None:
            kind_filter = (
                object_kind
                if isinstance(object_kind, CorpusObjectKind)
                else CorpusObjectKind(str(object_kind))
            )
        family_filter = None if family is None else str(family)
        profile_filter = None if profile is None else str(profile)
        with self._lock:
            cids: list[str] = []
            for cid, record in self._index.items():
                if kind_filter is not None and record.object_kind is not kind_filter:
                    continue
                if family_filter is not None and record.family != family_filter:
                    continue
                if profile_filter is not None and record.profile != profile_filter:
                    continue
                if cid in self._revocations and self._revocations[cid]:
                    continue
                if cid in self._contradictions and self._contradictions[cid]:
                    continue
                cids.append(cid)
            return tuple(sorted(cids))

    def get_envelope(
        self,
        content_cid: str,
        *,
        authoritative_only: bool = True,
    ) -> ArtifactEnvelope:
        """Load a typed envelope after authority and integrity checks.

        Raises :class:`ProofCorpusDuckDBRepositoryAuthorityError` when the
        CID is revoked or contradicted and *authoritative_only* is True.
        """

        hit = self.lookup(
            content_cid,
            authoritative_only=authoritative_only,
            expected_kind=CorpusObjectKind.ENVELOPE,
        )
        if not hit.hit:
            if hit.reason is AuthoritativeHitReason.TAMPERED:
                raise ProofCorpusDuckDBRepositoryIntegrityError(
                    f"envelope {content_cid!r} failed integrity (tampered)"
                )
            raise ProofCorpusDuckDBRepositoryError(
                f"envelope {content_cid!r} not found"
            )
        if authoritative_only and not hit.authoritative:
            raise ProofCorpusDuckDBRepositoryAuthorityError(
                f"envelope {content_cid!r} is not authoritative "
                f"(reason={hit.reason.value})"
            )
        data = self.get_bytes(content_cid)
        try:
            payload = json.loads(data.decode("utf-8"))
            envelope = ArtifactEnvelope.from_dict(
                as_mapping(payload, "artifact envelope")
            )
        except (
            UnicodeError,
            json.JSONDecodeError,
            ProofCorpusSchemaError,
            ProofCorpusIntegrityError,
        ) as exc:
            raise ProofCorpusDuckDBRepositoryIntegrityError(
                f"envelope {content_cid!r} failed reconstruction: {exc}"
            ) from exc
        if envelope.content_cid != content_cid:
            raise ProofCorpusDuckDBRepositoryIntegrityError(
                "reconstructed envelope content_cid drifted from lookup CID"
            )
        return envelope

    def get_manifest(
        self,
        content_cid: str,
        *,
        authoritative_only: bool = True,
    ) -> ProofCorpusManifest:
        hit = self.lookup(
            content_cid,
            authoritative_only=authoritative_only,
            expected_kind=CorpusObjectKind.MANIFEST,
        )
        if not hit.hit:
            if hit.reason is AuthoritativeHitReason.TAMPERED:
                raise ProofCorpusDuckDBRepositoryIntegrityError(
                    f"manifest {content_cid!r} failed integrity (tampered)"
                )
            raise ProofCorpusDuckDBRepositoryError(
                f"manifest {content_cid!r} not found"
            )
        if authoritative_only and not hit.authoritative:
            raise ProofCorpusDuckDBRepositoryAuthorityError(
                f"manifest {content_cid!r} is not authoritative "
                f"(reason={hit.reason.value})"
            )
        data = self.get_bytes(content_cid)
        try:
            payload = json.loads(data.decode("utf-8"))
            return ProofCorpusManifest.from_dict(
                as_mapping(payload, "proof corpus manifest")
            )
        except (
            UnicodeError,
            json.JSONDecodeError,
            ProofCorpusManifestError,
            ProofCorpusManifestIntegrityError,
        ) as exc:
            raise ProofCorpusDuckDBRepositoryIntegrityError(
                f"manifest {content_cid!r} failed reconstruction: {exc}"
            ) from exc

    def get_revocation(
        self,
        content_cid: str,
        *,
        authoritative_only: bool = True,
    ) -> ProofRevocationSnapshot:
        hit = self.lookup(
            content_cid,
            authoritative_only=authoritative_only,
            expected_kind=CorpusObjectKind.REVOCATION,
        )
        if not hit.hit:
            if hit.reason is AuthoritativeHitReason.TAMPERED:
                raise ProofCorpusDuckDBRepositoryIntegrityError(
                    f"revocation {content_cid!r} failed integrity (tampered)"
                )
            raise ProofCorpusDuckDBRepositoryError(
                f"revocation {content_cid!r} not found"
            )
        if authoritative_only and not hit.authoritative:
            raise ProofCorpusDuckDBRepositoryAuthorityError(
                f"revocation {content_cid!r} is not authoritative "
                f"(reason={hit.reason.value})"
            )
        data = self.get_bytes(content_cid)
        try:
            payload = json.loads(data.decode("utf-8"))
            return ProofRevocationSnapshot.from_dict(
                as_mapping(payload, "revocation snapshot")
            )
        except (
            UnicodeError,
            json.JSONDecodeError,
            ProofRevocationError,
            ProofRevocationIntegrityError,
        ) as exc:
            raise ProofCorpusDuckDBRepositoryIntegrityError(
                f"revocation {content_cid!r} failed reconstruction: {exc}"
            ) from exc

    def get_attestation_payload(
        self,
        content_cid: str,
        *,
        authoritative_only: bool = True,
    ) -> dict[str, Any]:
        hit = self.lookup(
            content_cid,
            authoritative_only=authoritative_only,
            expected_kind=CorpusObjectKind.ATTESTATION,
        )
        if not hit.hit:
            if hit.reason is AuthoritativeHitReason.TAMPERED:
                raise ProofCorpusDuckDBRepositoryIntegrityError(
                    f"attestation {content_cid!r} failed integrity (tampered)"
                )
            raise ProofCorpusDuckDBRepositoryError(
                f"attestation {content_cid!r} not found"
            )
        if authoritative_only and not hit.authoritative:
            raise ProofCorpusDuckDBRepositoryAuthorityError(
                f"attestation {content_cid!r} is not authoritative "
                f"(reason={hit.reason.value})"
            )
        data = self.get_bytes(content_cid)
        try:
            payload = json.loads(data.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise ProofCorpusDuckDBRepositoryIntegrityError(
                f"attestation {content_cid!r} failed reconstruction: {exc}"
            ) from exc
        if not isinstance(payload, Mapping):
            raise ProofCorpusDuckDBRepositoryIntegrityError(
                f"attestation {content_cid!r} payload is not a mapping"
            )
        return dict(payload)

    # -- bulk / inspection ---------------------------------------------------

    def cids(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(sorted(self._index))

    def records(
        self, *, object_kind: CorpusObjectKind | str | None = None
    ) -> tuple[CorpusIndexRecord, ...]:
        kind_filter: CorpusObjectKind | None = None
        if object_kind is not None:
            kind_filter = (
                object_kind
                if isinstance(object_kind, CorpusObjectKind)
                else CorpusObjectKind(str(object_kind))
            )
        with self._lock:
            items = list(self._index.values())
        if kind_filter is not None:
            items = [item for item in items if item.object_kind is kind_filter]
        return tuple(sorted(items, key=lambda item: item.content_cid))

    def clear(self) -> None:
        with self._lock:
            self._index.clear()
            self._revocations.clear()
            self._contradictions.clear()
            self._revocation_snapshots.clear()
            self._access.clear()
            self._blobs.clear()
            for key in self._stats:
                self._stats[key] = 0

    def inject_tampered_blob_for_tests(
        self, content_cid: str, tampered_data: bytes
    ) -> None:
        """Test helper: overwrite CA bytes without updating digests.

        Production code paths never call this.  Used solely to prove
        fail-closed tamper detection in unit tests.
        """

        cid = require_text(content_cid, "content_cid")
        data = _require_bytes(tampered_data, "tampered_data")
        with self._lock:
            existing = self._blobs._blobs.get(cid)
            if existing is None:
                raise ProofCorpusDuckDBRepositoryError(
                    f"no blob for CID {cid!r}"
                )
            # Bypass ContentAddressedBlob integrity to simulate external
            # storage corruption.
            object.__setattr__(existing, "data", data)


def build_proof_corpus_duckdb_repository(
    *,
    connection: Any | None = None,
    blob_store: ContentAddressedBlobStore | None = None,
    clock: Callable[[], float] | None = None,
) -> ProofCorpusDuckDBRepository:
    """Construct a :class:`ProofCorpusDuckDBRepository` (factory sugar)."""

    return ProofCorpusDuckDBRepository(
        connection=connection,
        blob_store=blob_store,
        clock=clock,
    )


def project_envelopes(
    repository: ProofCorpusDuckDBRepository,
    envelopes: Iterable[ArtifactEnvelope | Mapping[str, Any]],
) -> tuple[CorpusIndexRecord, ...]:
    """Index a batch of envelopes; returns the resulting index records."""

    if not isinstance(repository, ProofCorpusDuckDBRepository):
        raise ProofCorpusDuckDBRepositoryError(
            "repository must be a ProofCorpusDuckDBRepository"
        )
    return tuple(repository.put_envelope(item) for item in envelopes)


__all__ = [
    "AuthoritativeHit",
    "AuthoritativeHitReason",
    "CORPUS_CATALOG_DDL",
    "CORPUS_CATALOG_NAME",
    "CORPUS_CATALOG_TABLES",
    "ContentAddressedBlob",
    "ContentAddressedBlobStore",
    "CorpusIndexRecord",
    "CorpusObjectKind",
    "PROOF_CORPUS_DUCKDB_REPOSITORY_INTERFACE",
    "PROOF_CORPUS_DUCKDB_REPOSITORY_SCHEMA_VERSION",
    "ProofCorpusDuckDBRepository",
    "ProofCorpusDuckDBRepositoryAuthorityError",
    "ProofCorpusDuckDBRepositoryError",
    "ProofCorpusDuckDBRepositoryIntegrityError",
    "build_proof_corpus_duckdb_repository",
    "project_envelopes",
    "repository_canonical_bytes",
    "repository_content_digest",
]
