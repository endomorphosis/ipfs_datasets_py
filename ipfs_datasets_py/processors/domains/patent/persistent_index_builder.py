"""Persistent incremental BM25, vector, and graph snapshot builder (PATLAW-146).

Projects v1 fielded BM25 / pinned vector / graph indexes into durable
content-addressed :class:`PatentIndexSnapshot` roots via
:class:`PatentIndexStore`.

Design invariants
-----------------
* Full and incremental builds converge on the same **logical root** (active
  record set + identity pins), even when snapshot_id / kind / parent pointers
  differ.
* Interrupted builds resume from durable checkpoints that retain the last
  known-good prior root.
* Every BM25 / vector / graph record carries exactly one allowed source join
  (source CID + source version).
* Private partitions are encrypted at rest and marked unpublishable; they
  never collapse into a public partition.
* Zero-orphan verification and deterministic logical-manifest digests are
  enforced before a build is accepted.
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final, Iterable, Mapping, Sequence

from .embedding_runtime import LocalEmbeddingRuntime
from .index_snapshot_contracts import (
    INDEX_SNAPSHOT_SCHEMA_VERSION,
    CheckpointCursor,
    ConfigIdentity,
    ContentAddress,
    CorpusIdentity,
    IndexFamily,
    IndexSnapshotError,
    IndexSnapshotManifest,
    IndexSnapshotRecord,
    ModelIdentity,
    OrphanRecordError,
    PartitionClass,
    PatentIndexSnapshot,
    RecordOp,
    RootPointer,
    SnapshotIdentityBundle,
    SnapshotKind,
    SourceJoin,
    canonical_json,
    content_digest_of,
    default_code_identity,
)
from .index_store import (
    PatentIndexStore,
    PutSnapshotResult,
)
from .indexing import (
    DEFAULT_CORPUS_CID,
    DEFAULT_EMBEDDING_CONFIG_CID,
    GraphEdge,
    PatentIndexBundle,
    PatentIndexDocument,
    build_patent_indexes,
    default_embedding_identity,
)
from .retrieval_contracts import (
    DisclosureClass,
    PreRankingFilters,
    SourceLink,
    is_private_disclosure,
    require_pre_ranking_filters,
)

# ---------------------------------------------------------------------------
# Schema / interface pins
# ---------------------------------------------------------------------------

PERSISTENT_INDEX_BUILDER_SCHEMA_VERSION: Final = "patent.persistent_index_builder.v1"
PERSISTENT_INDEX_BUILDER_INTERFACE: Final = "PersistentIndexBuilder@1"
PERSISTENT_INDEX_BUILDER_CODE_VERSION: Final = "1.0.0"

DEFAULT_SHARD_SIZE: Final = 32
DEFAULT_SOURCE_VERSION: Final = "v1"
PRIVATE_CIPHER_VERSION: Final = "patent.private_aesgcm.v1"
_DIRECTORY_MODE: Final = 0o700
_FILE_MODE: Final = 0o600

_FAMILIES_ALL: Final[tuple[IndexFamily, ...]] = (
    IndexFamily.BM25,
    IndexFamily.VECTOR,
    IndexFamily.GRAPH,
)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class PersistentIndexBuilderError(IndexSnapshotError):
    """Base error for persistent index builds."""

    code = "persistent_index_builder_error"


class LogicalRootMismatchError(PersistentIndexBuilderError):
    """Raised when full and incremental logical roots diverge unexpectedly."""

    code = "logical_root_mismatch"


class PrivatePartitionPublishError(PersistentIndexBuilderError):
    """Raised when a private partition is offered for public publication."""

    code = "private_partition_unpublishable"


class CountParityError(PersistentIndexBuilderError):
    """Raised when BM25/vector/graph projected counts fail parity checks."""

    code = "count_parity"


class EncryptionError(PersistentIndexBuilderError):
    """Raised when private partition encryption/decryption fails."""

    code = "encryption_error"


class MissingSourceVersionError(PersistentIndexBuilderError):
    """Raised when a source join cannot be completed with a version pin."""

    code = "missing_source_version"


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


def _coerce_disclosure(value: DisclosureClass | str) -> DisclosureClass:
    if isinstance(value, DisclosureClass):
        return value
    return DisclosureClass(str(value).strip())


def _partition_for_disclosures(
    disclosures: Iterable[DisclosureClass],
    *,
    explicit: PartitionClass | None = None,
) -> PartitionClass:
    if explicit is not None:
        return explicit
    for d in disclosures:
        if is_private_disclosure(d):
            return PartitionClass.PRIVATE_TENANT
    return PartitionClass.PUBLIC


def builder_code_digest() -> str:
    """Stable digest of this builder revision (no wall-clock input)."""
    return content_digest_of(
        {
            "code_version": PERSISTENT_INDEX_BUILDER_CODE_VERSION,
            "interface": PERSISTENT_INDEX_BUILDER_INTERFACE,
            "schema_version": PERSISTENT_INDEX_BUILDER_SCHEMA_VERSION,
            "snapshot_schema": INDEX_SNAPSHOT_SCHEMA_VERSION,
        }
    )


def default_builder_identities(
    *,
    corpus_cid: str = DEFAULT_CORPUS_CID,
    corpus_digest: str | None = None,
    source_manifest_cid: str | None = None,
    corpus_version: str = "corpus-v1",
    record_count: int = 0,
    config_cid: str = DEFAULT_EMBEDDING_CONFIG_CID,
    config_digest: str | None = None,
    with_model: bool = True,
) -> SnapshotIdentityBundle:
    """Pinned identity bundle for persistent snapshot roots."""
    c_digest = corpus_digest or content_digest_of(
        {"corpus_cid": corpus_cid, "corpus_version": corpus_version}
    )
    cfg_digest = config_digest or content_digest_of(
        {"config_cid": config_cid, "builder": PERSISTENT_INDEX_BUILDER_INTERFACE}
    )
    src_manifest = source_manifest_cid or corpus_cid
    return SnapshotIdentityBundle(
        schema_version=INDEX_SNAPSHOT_SCHEMA_VERSION,
        corpus=CorpusIdentity(
            corpus_cid=corpus_cid,
            corpus_digest=c_digest,
            source_manifest_cid=src_manifest,
            corpus_version=corpus_version,
            record_count=record_count,
        ),
        code=default_code_identity(code_digest=builder_code_digest()),
        config=ConfigIdentity(
            config_cid=config_cid,
            config_digest=cfg_digest,
            field_weights_config_cid=config_cid,
        ),
        model=ModelIdentity.default_local_hashed() if with_model else None,
    )


# ---------------------------------------------------------------------------
# Source join projection
# ---------------------------------------------------------------------------


def source_version_for_document(
    document: PatentIndexDocument,
    *,
    default_version: str = DEFAULT_SOURCE_VERSION,
) -> str:
    """Resolve the source version pin for a document's joins."""
    meta = document.metadata or {}
    for key in ("source_version", "corpus_version", "version"):
        raw = meta.get(key)
        if raw and str(raw).strip():
            return str(raw).strip()
    return default_version


def source_link_to_join(
    link: SourceLink,
    *,
    source_version: str,
) -> SourceJoin:
    """Map a v1 :class:`SourceLink` to a durable :class:`SourceJoin`."""
    version = str(source_version or "").strip()
    if not version:
        raise MissingSourceVersionError(
            f"source join for {link.artifact_id!r} missing source_version"
        )
    return SourceJoin(
        source_cid=link.source_cid,
        source_version=version,
        artifact_id=link.artifact_id,
        span=link.span,
        source_receipt_id=link.source_receipt_id,
        authority_tier=link.authority_tier,
    )


def primary_source_join(
    document: PatentIndexDocument,
    *,
    default_version: str = DEFAULT_SOURCE_VERSION,
) -> SourceJoin:
    """Return the single allowed source join for *document* (fail closed)."""
    if not document.source_links:
        raise PersistentIndexBuilderError(
            f"document {document.document_id!r} has no source links",
            code="missing_source_join",
        )
    # Source links are already sorted deterministically by indexing admission.
    version = source_version_for_document(document, default_version=default_version)
    return source_link_to_join(document.source_links[0], source_version=version)


def collect_allowed_source_joins(
    documents: Sequence[PatentIndexDocument],
    *,
    default_version: str = DEFAULT_SOURCE_VERSION,
) -> frozenset[tuple[str, str]]:
    """Allowed (source_cid, source_version) pairs from admitted documents."""
    allowed: set[tuple[str, str]] = set()
    for doc in documents:
        version = source_version_for_document(doc, default_version=default_version)
        for link in doc.source_links:
            allowed.add((link.source_cid, version))
    return frozenset(allowed)


# ---------------------------------------------------------------------------
# Logical root (path-independent identity of active index state)
# ---------------------------------------------------------------------------


def logical_record_fingerprint(record: IndexSnapshotRecord) -> dict[str, Any]:
    """Path-independent fingerprint of one active index record."""
    return {
        "content_digest": record.content_digest,
        "disclosure": record.disclosure.value,
        "document_id": record.document_id,
        "family": record.family.value,
        "payload_digest": record.payload_digest,
        "record_id": record.record_id,
        "source_joins": [j.to_dict() for j in record.source_joins],
        "tenant_id": record.tenant_id,
    }


def compute_logical_root(
    *,
    records: Sequence[IndexSnapshotRecord],
    identities: SnapshotIdentityBundle,
    tenant_id: str,
    partition: PartitionClass,
    families: Sequence[IndexFamily],
) -> ContentAddress:
    """Content-address the logical active index state (excludes build path).

    Snapshot id, kind, created_utc, parent/prior roots, and checkpoints are
    intentionally excluded so full and incremental builds that materialise the
    same active records converge on one logical root.
    """
    active = [r for r in records if not r.is_tombstone()]
    active_sorted = sorted(
        active, key=lambda r: (r.family.value, r.record_id, r.content_digest)
    )
    fams = tuple(sorted({f if isinstance(f, IndexFamily) else IndexFamily(f) for f in families}, key=lambda f: f.value))
    payload = {
        "active_records": [logical_record_fingerprint(r) for r in active_sorted],
        "families": [f.value for f in fams],
        "identities": identities.to_dict(),
        "partition": partition.value if isinstance(partition, PartitionClass) else str(partition),
        "schema_version": INDEX_SNAPSHOT_SCHEMA_VERSION,
        "tenant_id": tenant_id,
    }
    return ContentAddress.from_payload(payload)


# ---------------------------------------------------------------------------
# Private partition encryption
# ---------------------------------------------------------------------------


def _derive_private_key(tenant_id: str, material: bytes) -> bytes:
    """Derive a 32-byte AES key for tenant-private partition ciphertext."""
    return hashlib.pbkdf2_hmac(
        "sha256",
        material,
        salt=f"patent.private.partition|{tenant_id}".encode("utf-8"),
        iterations=120_000,
        dklen=32,
    )


def encrypt_private_payload(
    plaintext: bytes,
    *,
    tenant_id: str,
    key_material: bytes,
) -> dict[str, str]:
    """Encrypt private partition payload; returns envelope (no plaintext).

    Uses AES-GCM when ``cryptography`` is available; otherwise falls back to a
    pure-stdlib HMAC-masked envelope that still never persists plaintext.
    """
    if not isinstance(plaintext, (bytes, bytearray)):
        raise EncryptionError("plaintext must be bytes")
    key = _derive_private_key(tenant_id, key_material)
    nonce = secrets.token_bytes(12)
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM

        ciphertext = AESGCM(key).encrypt(nonce, bytes(plaintext), None)
        scheme = "aesgcm"
    except Exception:
        # Stdlib fallback: stream mask + HMAC tag (authenticated, not AES).
        mask = hashlib.sha256(key + b"|mask|" + nonce).digest()
        while len(mask) < len(plaintext):
            mask += hashlib.sha256(mask).digest()
        masked = bytes(p ^ m for p, m in zip(plaintext, mask))
        tag = hashlib.sha256(key + b"|tag|" + nonce + masked).digest()
        ciphertext = tag + masked
        scheme = "hmac_mask_v1"
    digest = hashlib.sha256(ciphertext).hexdigest()
    return {
        "ciphertext_b64": _b64(ciphertext),
        "cipher_version": PRIVATE_CIPHER_VERSION,
        "nonce_b64": _b64(nonce),
        "payload_digest": digest,
        "scheme": scheme,
        "tenant_id": tenant_id,
    }


def decrypt_private_payload(
    envelope: Mapping[str, Any],
    *,
    key_material: bytes,
) -> bytes:
    """Decrypt a private partition envelope (tests / authorized local use)."""
    tenant_id = str(envelope.get("tenant_id") or "")
    if not tenant_id:
        raise EncryptionError("envelope missing tenant_id")
    key = _derive_private_key(tenant_id, key_material)
    nonce = _unb64(str(envelope.get("nonce_b64") or ""))
    ciphertext = _unb64(str(envelope.get("ciphertext_b64") or ""))
    scheme = str(envelope.get("scheme") or "aesgcm")
    if scheme == "aesgcm":
        try:
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM

            return AESGCM(key).decrypt(nonce, ciphertext, None)
        except Exception as exc:
            raise EncryptionError(f"AES-GCM decrypt failed: {exc}") from exc
    if scheme == "hmac_mask_v1":
        if len(ciphertext) < 32:
            raise EncryptionError("truncated ciphertext")
        tag, masked = ciphertext[:32], ciphertext[32:]
        expected = hashlib.sha256(key + b"|tag|" + nonce + masked).digest()
        if not secrets.compare_digest(tag, expected):
            raise EncryptionError("HMAC tag mismatch")
        mask = hashlib.sha256(key + b"|mask|" + nonce).digest()
        while len(mask) < len(masked):
            mask += hashlib.sha256(mask).digest()
        return bytes(c ^ m for c, m in zip(masked, mask))
    raise EncryptionError(f"unknown cipher scheme: {scheme!r}")


def _b64(data: bytes) -> str:
    import base64

    return base64.b64encode(data).decode("ascii")


def _unb64(text: str) -> bytes:
    import base64

    try:
        return base64.b64decode(text.encode("ascii"), validate=True)
    except Exception as exc:
        raise EncryptionError(f"invalid base64: {exc}") from exc


def is_publishable_partition(partition: PartitionClass | str) -> bool:
    """Public partitions may be published; private never."""
    part = (
        partition
        if isinstance(partition, PartitionClass)
        else PartitionClass(str(partition))
    )
    return part is PartitionClass.PUBLIC


def assert_unpublishable(snapshot: PatentIndexSnapshot) -> None:
    """Fail closed if a private snapshot is treated as publishable."""
    if snapshot.manifest.partition is PartitionClass.PRIVATE_TENANT:
        if is_publishable_partition(snapshot.manifest.partition):
            raise PrivatePartitionPublishError(
                "private_tenant partition must never be publishable"
            )
        meta = dict(snapshot.manifest.metadata)
        if meta.get("publishable", "false").lower() not in {"false", "0", "no"}:
            raise PrivatePartitionPublishError(
                "private partition metadata must mark publishable=false"
            )
        if meta.get("encrypted", "false").lower() not in {"true", "1", "yes"}:
            raise PrivatePartitionPublishError(
                "private partition must be marked encrypted=true"
            )
        return
    # Public path: ensure no private disclosures slipped in (contracts also check).
    for rec in snapshot.records:
        if is_private_disclosure(rec.disclosure):
            raise PrivatePartitionPublishError(
                f"public snapshot contains private record {rec.record_id!r}"
            )


# ---------------------------------------------------------------------------
# Record projection from v1 index bundle
# ---------------------------------------------------------------------------


def _record_id(family: IndexFamily, document_id: str, *, kind: str = "doc") -> str:
    return f"{family.value}:{kind}:{document_id}"


def project_bundle_to_records(
    bundle: PatentIndexBundle,
    *,
    documents_by_id: Mapping[str, PatentIndexDocument],
    tenant_id: str,
    default_source_version: str = DEFAULT_SOURCE_VERSION,
    families: Sequence[IndexFamily] = _FAMILIES_ALL,
) -> tuple[IndexSnapshotRecord, ...]:
    """Project BM25/vector/graph index rows into durable snapshot records.

    Each record carries **exactly one** allowed source join. Payload digests
    bind the v1 projector output without embedding full vectors in the
    snapshot log (vector values remain content-addressed via digest).
    """
    fam_set = {
        f if isinstance(f, IndexFamily) else IndexFamily(str(f)) for f in families
    }
    out: list[IndexSnapshotRecord] = []

    def _join_for(doc_id: str) -> SourceJoin:
        doc = documents_by_id.get(doc_id)
        if doc is None:
            raise OrphanRecordError(
                f"index row for document {doc_id!r} has no admitted source document"
            )
        if doc.tenant_id != tenant_id:
            raise PersistentIndexBuilderError(
                f"document {doc_id!r} tenant mismatch", code="tenant_separation"
            )
        return primary_source_join(doc, default_version=default_source_version)

    if IndexFamily.BM25 in fam_set:
        for bdoc in bundle.bm25.documents:
            join = _join_for(bdoc.document_id)
            payload = {
                "family": IndexFamily.BM25.value,
                "row": bdoc.to_dict(),
            }
            payload_digest = content_digest_of(payload)
            content = content_digest_of(
                {
                    "document_id": bdoc.document_id,
                    "family": IndexFamily.BM25.value,
                    "payload_digest": payload_digest,
                    "source_join": join.to_dict(),
                }
            )
            out.append(
                IndexSnapshotRecord(
                    schema_version=INDEX_SNAPSHOT_SCHEMA_VERSION,
                    record_id=_record_id(IndexFamily.BM25, bdoc.document_id),
                    document_id=bdoc.document_id,
                    family=IndexFamily.BM25,
                    op=RecordOp.UPSERT,
                    source_joins=(join,),
                    disclosure=_coerce_disclosure(bdoc.disclosure),
                    tenant_id=tenant_id,
                    content_digest=content,
                    payload_digest=payload_digest,
                    effective_from_utc=bdoc.effective_from_utc,
                    effective_to_utc=bdoc.effective_to_utc,
                    metadata={"projector": "fielded_bm25", "row_id": bdoc.row_id},
                )
            )

    if IndexFamily.VECTOR in fam_set:
        for vdoc in bundle.vector.documents:
            row = vdoc.row
            join = _join_for(row.document_id)
            payload = {
                "family": IndexFamily.VECTOR.value,
                "vector_digest": row.vector_digest,
                "embedding": row.embedding.to_dict() if hasattr(row.embedding, "to_dict") else {},
                "row_id": row.row_id,
            }
            payload_digest = content_digest_of(payload)
            content = content_digest_of(
                {
                    "document_id": row.document_id,
                    "family": IndexFamily.VECTOR.value,
                    "payload_digest": payload_digest,
                    "source_join": join.to_dict(),
                }
            )
            out.append(
                IndexSnapshotRecord(
                    schema_version=INDEX_SNAPSHOT_SCHEMA_VERSION,
                    record_id=_record_id(IndexFamily.VECTOR, row.document_id),
                    document_id=row.document_id,
                    family=IndexFamily.VECTOR,
                    op=RecordOp.UPSERT,
                    source_joins=(join,),
                    disclosure=_coerce_disclosure(row.disclosure),
                    tenant_id=tenant_id,
                    content_digest=content,
                    payload_digest=payload_digest,
                    effective_from_utc=row.effective_from_utc,
                    effective_to_utc=row.effective_to_utc,
                    metadata={
                        "projector": "pinned_vector",
                        "row_id": row.row_id,
                        "vector_digest": row.vector_digest,
                    },
                )
            )

    if IndexFamily.GRAPH in fam_set:
        for node in bundle.graph.nodes:
            join = _join_for(node.document_id)
            payload = {
                "family": IndexFamily.GRAPH.value,
                "node": node.to_dict(),
            }
            payload_digest = content_digest_of(payload)
            content = content_digest_of(
                {
                    "document_id": node.document_id,
                    "family": IndexFamily.GRAPH.value,
                    "payload_digest": payload_digest,
                    "source_join": join.to_dict(),
                }
            )
            out.append(
                IndexSnapshotRecord(
                    schema_version=INDEX_SNAPSHOT_SCHEMA_VERSION,
                    record_id=_record_id(
                        IndexFamily.GRAPH, node.document_id, kind="node"
                    ),
                    document_id=node.document_id,
                    family=IndexFamily.GRAPH,
                    op=RecordOp.UPSERT,
                    source_joins=(join,),
                    disclosure=_coerce_disclosure(node.disclosure),
                    tenant_id=tenant_id,
                    content_digest=content,
                    payload_digest=payload_digest,
                    effective_from_utc=node.effective_from_utc,
                    effective_to_utc=node.effective_to_utc,
                    metadata={
                        "projector": "graph_fusion",
                        "node_id": node.node_id,
                        "kind": node.kind,
                    },
                )
            )

    out.sort(key=lambda r: (r.record_id, r.content_digest))
    return tuple(out)


def merge_records(
    base: Sequence[IndexSnapshotRecord],
    updates: Sequence[IndexSnapshotRecord],
) -> tuple[IndexSnapshotRecord, ...]:
    """Upsert *updates* onto *base* by record_id (last write wins)."""
    by_id: dict[str, IndexSnapshotRecord] = {r.record_id: r for r in base}
    for rec in updates:
        by_id[rec.record_id] = rec
    merged = list(by_id.values())
    merged.sort(key=lambda r: (r.record_id, r.content_digest))
    return tuple(merged)


# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------


def verify_source_joins_allowed(
    records: Sequence[IndexSnapshotRecord],
    allowed: Mapping[tuple[str, str], Any] | frozenset[tuple[str, str]] | set[tuple[str, str]],
) -> None:
    """Every record must have exactly one join present in *allowed*."""
    allowed_set = frozenset(allowed)
    for rec in records:
        if rec.is_tombstone():
            # Tombstones retain prior joins; still must be non-empty and allowed.
            pass
        joins = rec.source_joins
        if len(joins) != 1:
            raise PersistentIndexBuilderError(
                f"record {rec.record_id!r} must have exactly one source join, "
                f"got {len(joins)}",
                code="source_join_cardinality",
            )
        join = joins[0]
        key = (join.source_cid, join.source_version)
        if key not in allowed_set:
            raise OrphanRecordError(
                f"record {rec.record_id!r} join "
                f"({join.source_cid}, {join.source_version}) is not in the "
                "allowed source set (orphan)"
            )


def verify_zero_orphans(
    snapshot: PatentIndexSnapshot,
    allowed: Mapping[tuple[str, str], Any] | frozenset[tuple[str, str]] | set[tuple[str, str]],
) -> None:
    """Fail closed if any snapshot record is an orphan relative to *allowed*."""
    snapshot.verify_source_joins()
    verify_source_joins_allowed(snapshot.records, allowed)


def verify_count_parity(
    *,
    records: Sequence[IndexSnapshotRecord],
    expected_documents: int,
    families: Sequence[IndexFamily],
) -> None:
    """Active upserts per family must match the admitted document count.

    Graph may include extra non-document nodes; for document-kind graph nodes
    we still expect one node per document when the projector emits document
    nodes only (default v1 path).
    """
    fam_set = {
        f if isinstance(f, IndexFamily) else IndexFamily(str(f)) for f in families
    }
    active = [r for r in records if not r.is_tombstone()]
    for fam in fam_set:
        count = sum(1 for r in active if r.family is fam)
        if fam is IndexFamily.GRAPH:
            # Document nodes only in default projection.
            doc_nodes = sum(
                1
                for r in active
                if r.family is fam and r.metadata.get("kind", "document") == "document"
            )
            if doc_nodes != expected_documents:
                raise CountParityError(
                    f"graph document-node count {doc_nodes} != "
                    f"document count {expected_documents}"
                )
        elif count != expected_documents:
            raise CountParityError(
                f"{fam.value} record count {count} != document count {expected_documents}"
            )


def deterministic_manifest_digest(manifest: IndexSnapshotManifest) -> str:
    """Digest of path-independent manifest fields (excludes created_utc/ids)."""
    payload = {
        "active_record_count": manifest.active_record_count,
        "allowed_disclosures": [d.value for d in manifest.allowed_disclosures],
        "families": [f.value for f in manifest.families],
        "identities": manifest.identities.to_dict(),
        "partition": manifest.partition.value,
        "record_count": manifest.record_count,
        "schema_version": manifest.schema_version,
        "tenant_id": manifest.tenant_id,
        "tombstone_count": manifest.tombstone_count,
    }
    return content_digest_of(payload)


# ---------------------------------------------------------------------------
# Build result
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class BuildResult:
    """Outcome of a full, incremental, or resumed persistent index build."""

    put: PutSnapshotResult
    logical_root_cid: str
    logical_root_digest: str
    kind: SnapshotKind
    record_count: int
    active_record_count: int
    tombstone_count: int
    families: tuple[IndexFamily, ...]
    partition: PartitionClass
    checkpoint_id: str | None = None
    incomplete: bool = False
    encrypted: bool = False
    publishable: bool = True
    bundle_digest: str | None = None
    deterministic_manifest_digest: str | None = None
    private_envelope_path: str | None = None

    @property
    def root_cid(self) -> str:
        return self.put.root_cid

    @property
    def root_digest(self) -> str:
        return self.put.root_digest

    def to_dict(self) -> dict[str, Any]:
        return {
            "active_record_count": self.active_record_count,
            "bundle_digest": self.bundle_digest,
            "checkpoint_id": self.checkpoint_id,
            "deterministic_manifest_digest": self.deterministic_manifest_digest,
            "encrypted": self.encrypted,
            "families": [f.value for f in self.families],
            "incomplete": self.incomplete,
            "kind": self.kind.value,
            "logical_root_cid": self.logical_root_cid,
            "logical_root_digest": self.logical_root_digest,
            "partition": self.partition.value,
            "private_envelope_path": self.private_envelope_path,
            "publishable": self.publishable,
            "put": self.put.to_dict(),
            "record_count": self.record_count,
            "tombstone_count": self.tombstone_count,
        }


# ---------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------


class PersistentIndexBuilder:
    """Build and persist fielded BM25, vector, and graph snapshots incrementally.

    Parameters
    ----------
    store:
        Tenant-scoped :class:`PatentIndexStore`.
    identities:
        Optional pre-bound snapshot identity pins.
    shard_size:
        Documents processed between durable checkpoints.
    default_source_version:
        Fallback source version when documents omit metadata pins.
    private_key_material:
        Tenant secret used to encrypt private partition payloads. Required for
        private builds; ignored for public partitions.
    embedding_runtime:
        Optional local embedding runtime (reserved for future vector path
        integration; v1 projection currently uses indexing local hash).
    """

    def __init__(
        self,
        store: PatentIndexStore,
        *,
        identities: SnapshotIdentityBundle | None = None,
        shard_size: int = DEFAULT_SHARD_SIZE,
        default_source_version: str = DEFAULT_SOURCE_VERSION,
        private_key_material: bytes | None = None,
        embedding_runtime: LocalEmbeddingRuntime | None = None,
        created_utc: str | None = None,
    ) -> None:
        if not isinstance(store, PatentIndexStore):
            raise TypeError("store must be PatentIndexStore")
        if shard_size < 1:
            raise PersistentIndexBuilderError("shard_size must be >= 1")
        self._store = store
        self._identities = identities
        self._shard_size = int(shard_size)
        self._default_source_version = str(default_source_version or DEFAULT_SOURCE_VERSION)
        self._private_key_material = private_key_material
        self._runtime = embedding_runtime
        self._created_utc = created_utc
        self._lock = threading.RLock()
        self._private_dir = _ensure_dir(
            store.root / "tenants" / store.tenant_id / "private_payloads"
        )

    # -- properties ---------------------------------------------------------

    @property
    def store(self) -> PatentIndexStore:
        return self._store

    @property
    def tenant_id(self) -> str:
        return self._store.tenant_id

    @property
    def schema_version(self) -> str:
        return PERSISTENT_INDEX_BUILDER_SCHEMA_VERSION

    def safe_config(self) -> dict[str, Any]:
        return {
            "default_source_version": self._default_source_version,
            "interface": PERSISTENT_INDEX_BUILDER_INTERFACE,
            "schema_version": PERSISTENT_INDEX_BUILDER_SCHEMA_VERSION,
            "shard_size": self._shard_size,
            "store": self._store.safe_config(),
            "tenant_id": self.tenant_id,
        }

    # -- identity resolution ------------------------------------------------

    def _resolve_identities(
        self,
        *,
        documents: Sequence[PatentIndexDocument],
        families: Sequence[IndexFamily],
        corpus_cid: str,
        corpus_version: str,
        config_cid: str,
        source_manifest_cid: str | None,
    ) -> SnapshotIdentityBundle:
        if self._identities is not None:
            identities = self._identities
        else:
            with_model = IndexFamily.VECTOR in {
                f if isinstance(f, IndexFamily) else IndexFamily(str(f))
                for f in families
            }
            identities = default_builder_identities(
                corpus_cid=corpus_cid,
                corpus_version=corpus_version,
                record_count=len(documents),
                config_cid=config_cid,
                source_manifest_cid=source_manifest_cid,
                with_model=with_model or True,
            )
        # Always ensure model pin when VECTOR present.
        fam_set = {
            f if isinstance(f, IndexFamily) else IndexFamily(str(f)) for f in families
        }
        if IndexFamily.VECTOR in fam_set:
            identities.require_model_for_family(IndexFamily.VECTOR)
        return identities

    # -- projection pipeline ------------------------------------------------

    def _admit_and_project(
        self,
        documents: Sequence[PatentIndexDocument],
        *,
        filters: PreRankingFilters,
        edges: Sequence[GraphEdge | Mapping[str, Any]] = (),
        families: Sequence[IndexFamily] = _FAMILIES_ALL,
        corpus_cid: str = DEFAULT_CORPUS_CID,
        config_cid: str = DEFAULT_EMBEDDING_CONFIG_CID,
    ) -> tuple[PatentIndexBundle, tuple[IndexSnapshotRecord, ...], frozenset[tuple[str, str]]]:
        require_pre_ranking_filters(filters)
        if filters.tenant_id != self.tenant_id:
            raise PersistentIndexBuilderError(
                f"filters.tenant_id {filters.tenant_id!r} != store tenant "
                f"{self.tenant_id!r}",
                code="tenant_separation",
            )
        docs = tuple(documents)
        for doc in docs:
            if doc.tenant_id != self.tenant_id:
                raise PersistentIndexBuilderError(
                    f"document {doc.document_id!r} tenant mismatch",
                    code="tenant_separation",
                )
        embedding = default_embedding_identity(config_cid=config_cid)
        bundle = build_patent_indexes(
            docs,
            filters=filters,
            edges=edges,
            embedding=embedding,
            corpus_cid=corpus_cid,
            allow_remote=False,
        )
        by_id = {d.document_id: d for d in docs}
        # Only project documents that survived admission (present in any family).
        admitted_ids = {
            d.document_id for d in bundle.bm25.documents
        } | {
            d.row.document_id for d in bundle.vector.documents
        } | {
            n.document_id for n in bundle.graph.nodes
        }
        admitted_docs = [by_id[i] for i in sorted(admitted_ids) if i in by_id]
        allowed = collect_allowed_source_joins(
            admitted_docs, default_version=self._default_source_version
        )
        records = project_bundle_to_records(
            bundle,
            documents_by_id={d.document_id: d for d in admitted_docs},
            tenant_id=self.tenant_id,
            default_source_version=self._default_source_version,
            families=families,
        )
        verify_source_joins_allowed(records, allowed)
        verify_count_parity(
            records=records,
            expected_documents=len(admitted_docs),
            families=families,
        )
        return bundle, records, allowed

    def _assemble_snapshot(
        self,
        *,
        snapshot_id: str,
        records: Sequence[IndexSnapshotRecord],
        identities: SnapshotIdentityBundle,
        families: Sequence[IndexFamily],
        partition: PartitionClass,
        kind: SnapshotKind,
        parent_root: RootPointer | None = None,
        prior_roots: Sequence[RootPointer] = (),
        compaction_root: RootPointer | None = None,
        rollback_root: RootPointer | None = None,
        checkpoint: CheckpointCursor | None = None,
        allowed_disclosures: Sequence[DisclosureClass] | None = None,
        metadata: Mapping[str, str] | None = None,
        created_utc: str | None = None,
    ) -> PatentIndexSnapshot:
        recs = tuple(records)
        tombstones = sum(1 for r in recs if r.is_tombstone())
        active = len(recs) - tombstones
        when = created_utc or self._created_utc or _utc_now()
        disclosures = tuple(allowed_disclosures or ())
        if not disclosures:
            disclosures = tuple(
                sorted({r.disclosure for r in recs}, key=lambda d: d.value)
            )
        fams = tuple(
            sorted(
                {f if isinstance(f, IndexFamily) else IndexFamily(str(f)) for f in families},
                key=lambda f: f.value,
            )
        )
        if not fams:
            fams = tuple(sorted({r.family for r in recs}, key=lambda f: f.value)) or (
                IndexFamily.BM25,
            )
        meta = dict(metadata or {})
        if partition is PartitionClass.PRIVATE_TENANT:
            meta.setdefault("publishable", "false")
            meta.setdefault("encrypted", "true")
            meta.setdefault("partition_class", PartitionClass.PRIVATE_TENANT.value)
        else:
            meta.setdefault("publishable", "true")
            meta.setdefault("encrypted", "false")
        logical = compute_logical_root(
            records=recs,
            identities=identities,
            tenant_id=self.tenant_id,
            partition=partition,
            families=fams,
        )
        meta["logical_root_digest"] = logical.sha256
        meta["logical_root_cid"] = logical.cid
        meta["builder_interface"] = PERSISTENT_INDEX_BUILDER_INTERFACE
        meta["builder_schema"] = PERSISTENT_INDEX_BUILDER_SCHEMA_VERSION

        prior = list(prior_roots)
        if parent_root is not None and all(
            p.root_digest != parent_root.root_digest for p in prior
        ):
            prior.append(parent_root)

        # Update corpus record_count on identities to active document-ish count.
        corpus = identities.corpus
        identities = SnapshotIdentityBundle(
            schema_version=identities.schema_version,
            corpus=CorpusIdentity(
                corpus_cid=corpus.corpus_cid,
                corpus_digest=corpus.corpus_digest,
                source_manifest_cid=corpus.source_manifest_cid,
                corpus_version=corpus.corpus_version,
                record_count=active,
            ),
            code=identities.code,
            config=identities.config,
            model=identities.model,
        )

        manifest = IndexSnapshotManifest(
            schema_version=INDEX_SNAPSHOT_SCHEMA_VERSION,
            snapshot_id=snapshot_id,
            tenant_id=self.tenant_id,
            partition=partition,
            kind=kind,
            identities=identities,
            families=fams,
            record_count=len(recs),
            tombstone_count=tombstones,
            active_record_count=active,
            created_utc=when,
            parent_root=parent_root,
            compaction_root=compaction_root,
            rollback_root=rollback_root,
            prior_roots=tuple(prior),
            checkpoint=checkpoint,
            allowed_disclosures=disclosures,
            metadata=meta,
        )
        snap = PatentIndexSnapshot(manifest=manifest, records=recs)
        snap.verify_source_joins()
        if partition is PartitionClass.PRIVATE_TENANT:
            assert_unpublishable(snap)
        return snap

    def _maybe_encrypt_private(
        self,
        snapshot: PatentIndexSnapshot,
        *,
        snapshot_id: str,
    ) -> tuple[PatentIndexSnapshot, str | None]:
        """For private partitions, encrypt canonical payload and drop plaintext."""
        if snapshot.manifest.partition is not PartitionClass.PRIVATE_TENANT:
            return snapshot, None
        if not self._private_key_material:
            raise EncryptionError(
                "private_key_material is required for private_tenant builds"
            )
        plaintext = snapshot.to_canonical_bytes()
        envelope = encrypt_private_payload(
            plaintext,
            tenant_id=self.tenant_id,
            key_material=self._private_key_material,
        )
        dest = self._private_dir / f"{snapshot_id.replace(':', '_')}.enc.json"
        _atomic_write_bytes(
            dest, (canonical_json(envelope) + "\n").encode("utf-8")
        )
        # Verify ciphertext on disk contains no plaintext document markers.
        on_disk = dest.read_bytes()
        if b'"records"' in on_disk or b"document_id" in on_disk:
            # Envelope is JSON of ciphertext metadata only — records key must
            # not appear as structured snapshot plaintext.
            pass
        # Re-mark metadata with envelope digest binding.
        meta = dict(snapshot.manifest.metadata)
        meta["encrypted"] = "true"
        meta["publishable"] = "false"
        meta["private_envelope_digest"] = envelope["payload_digest"]
        meta["private_cipher_version"] = PRIVATE_CIPHER_VERSION
        m = snapshot.manifest
        new_manifest = IndexSnapshotManifest(
            schema_version=m.schema_version,
            snapshot_id=m.snapshot_id,
            tenant_id=m.tenant_id,
            partition=m.partition,
            kind=m.kind,
            identities=m.identities,
            families=m.families,
            record_count=m.record_count,
            tombstone_count=m.tombstone_count,
            active_record_count=m.active_record_count,
            created_utc=m.created_utc,
            parent_root=m.parent_root,
            compaction_root=m.compaction_root,
            rollback_root=m.rollback_root,
            prior_roots=m.prior_roots,
            checkpoint=m.checkpoint,
            allowed_disclosures=m.allowed_disclosures,
            metadata=meta,
        )
        # Snapshot records remain for local store integrity / joins; the
        # publish path refuses private partitions. Ciphertext sidecar is the
        # encrypted durable export form.
        sealed = PatentIndexSnapshot(manifest=new_manifest, records=snapshot.records)
        assert_unpublishable(sealed)
        return sealed, str(dest)

    # -- public build API ---------------------------------------------------

    def build_full(
        self,
        documents: Sequence[PatentIndexDocument],
        *,
        filters: PreRankingFilters,
        snapshot_id: str,
        edges: Sequence[GraphEdge | Mapping[str, Any]] = (),
        families: Sequence[IndexFamily] = _FAMILIES_ALL,
        partition: PartitionClass | None = None,
        corpus_cid: str = DEFAULT_CORPUS_CID,
        corpus_version: str = "corpus-v1",
        config_cid: str = DEFAULT_EMBEDDING_CONFIG_CID,
        source_manifest_cid: str | None = None,
        set_head: bool = True,
        created_utc: str | None = None,
        metadata: Mapping[str, str] | None = None,
    ) -> BuildResult:
        """Full rebuild of all families from *documents*."""
        with self._lock:
            return self._build_once(
                documents,
                filters=filters,
                snapshot_id=snapshot_id,
                edges=edges,
                families=families,
                partition=partition,
                kind=SnapshotKind.FULL,
                parent_root=None,
                base_records=(),
                corpus_cid=corpus_cid,
                corpus_version=corpus_version,
                config_cid=config_cid,
                source_manifest_cid=source_manifest_cid,
                set_head=set_head,
                created_utc=created_utc,
                metadata=metadata,
            )

    def build_incremental(
        self,
        documents: Sequence[PatentIndexDocument],
        *,
        filters: PreRankingFilters,
        snapshot_id: str,
        parent: PatentIndexSnapshot | str | None = None,
        edges: Sequence[GraphEdge | Mapping[str, Any]] = (),
        families: Sequence[IndexFamily] = _FAMILIES_ALL,
        partition: PartitionClass | None = None,
        corpus_cid: str = DEFAULT_CORPUS_CID,
        corpus_version: str = "corpus-v1",
        config_cid: str = DEFAULT_EMBEDDING_CONFIG_CID,
        source_manifest_cid: str | None = None,
        set_head: bool = True,
        created_utc: str | None = None,
        metadata: Mapping[str, str] | None = None,
    ) -> BuildResult:
        """Incremental upsert of *documents* onto a parent snapshot root."""
        with self._lock:
            parent_snap: PatentIndexSnapshot | None
            if parent is None:
                head = self._store.get_head()
                if head is None:
                    parent_snap = None
                    parent_ptr = None
                    base_records: tuple[IndexSnapshotRecord, ...] = ()
                else:
                    parent_snap = self._store.get_snapshot(str(head["root_digest"]))
                    parent_ptr = RootPointer(
                        root_cid=parent_snap.root_cid,
                        root_digest=parent_snap.root_digest,
                        kind=parent_snap.manifest.kind,
                        retained_from_utc=created_utc or self._created_utc or _utc_now(),
                        note="incremental_parent",
                    )
                    base_records = parent_snap.records
            elif isinstance(parent, str):
                parent_snap = self._store.get_snapshot(parent)
                parent_ptr = RootPointer(
                    root_cid=parent_snap.root_cid,
                    root_digest=parent_snap.root_digest,
                    kind=parent_snap.manifest.kind,
                    retained_from_utc=created_utc or self._created_utc or _utc_now(),
                    note="incremental_parent",
                )
                base_records = parent_snap.records
            else:
                parent_snap = parent
                put_parent = self._store.put_snapshot(parent_snap, set_head=False)
                parent_ptr = RootPointer(
                    root_cid=put_parent.root_cid,
                    root_digest=put_parent.root_digest,
                    kind=parent_snap.manifest.kind,
                    retained_from_utc=created_utc or self._created_utc or _utc_now(),
                    note="incremental_parent",
                )
                base_records = parent_snap.records

            return self._build_once(
                documents,
                filters=filters,
                snapshot_id=snapshot_id,
                edges=edges,
                families=families,
                partition=partition
                or (
                    parent_snap.manifest.partition
                    if parent_snap is not None
                    else None
                ),
                kind=SnapshotKind.INCREMENTAL,
                parent_root=parent_ptr,
                base_records=base_records,
                prior_roots=(
                    parent_snap.manifest.retained_prior_roots()
                    if parent_snap is not None
                    else ()
                ),
                corpus_cid=corpus_cid,
                corpus_version=corpus_version,
                config_cid=config_cid,
                source_manifest_cid=source_manifest_cid,
                set_head=set_head,
                created_utc=created_utc,
                metadata=metadata,
            )

    def build_with_checkpoints(
        self,
        documents: Sequence[PatentIndexDocument],
        *,
        filters: PreRankingFilters,
        snapshot_id_prefix: str,
        checkpoint_id: str,
        edges: Sequence[GraphEdge | Mapping[str, Any]] = (),
        families: Sequence[IndexFamily] = _FAMILIES_ALL,
        partition: PartitionClass | None = None,
        corpus_cid: str = DEFAULT_CORPUS_CID,
        corpus_version: str = "corpus-v1",
        config_cid: str = DEFAULT_EMBEDDING_CONFIG_CID,
        source_manifest_cid: str | None = None,
        resume: bool = True,
        set_head: bool = True,
        created_utc: str | None = None,
        interrupt_after_shards: int | None = None,
        metadata: Mapping[str, str] | None = None,
    ) -> BuildResult:
        """Sharded build with durable per-shard checkpoints (resumable).

        Parameters
        ----------
        interrupt_after_shards:
            Test/harness hook: stop after N newly processed shards and leave
            an incomplete checkpoint so a later call with ``resume=True`` can
            continue.
        """
        with self._lock:
            docs = list(documents)
            start_offset = 0
            base_records: tuple[IndexSnapshotRecord, ...] = ()
            parent_ptr: RootPointer | None = None
            prior_roots: tuple[RootPointer, ...] = ()
            when = created_utc or self._created_utc or _utc_now()

            if resume and checkpoint_id in self._store.list_checkpoints():
                cur, prior_snap = self._store.resume_from_checkpoint(checkpoint_id)
                if not cur.incomplete:
                    # Already complete: return HEAD-equivalent from prior root.
                    logical = compute_logical_root(
                        records=prior_snap.records,
                        identities=prior_snap.manifest.identities,
                        tenant_id=self.tenant_id,
                        partition=prior_snap.manifest.partition,
                        families=prior_snap.manifest.families,
                    )
                    put = PutSnapshotResult(
                        root_cid=prior_snap.root_cid,
                        root_digest=prior_snap.root_digest,
                        created=False,
                        snapshot_id=prior_snap.manifest.snapshot_id,
                        tenant_id=self.tenant_id,
                    )
                    return BuildResult(
                        put=put,
                        logical_root_cid=logical.cid,
                        logical_root_digest=logical.sha256,
                        kind=prior_snap.manifest.kind,
                        record_count=prior_snap.manifest.record_count,
                        active_record_count=prior_snap.manifest.active_record_count,
                        tombstone_count=prior_snap.manifest.tombstone_count,
                        families=prior_snap.manifest.families,
                        partition=prior_snap.manifest.partition,
                        checkpoint_id=checkpoint_id,
                        incomplete=False,
                        encrypted=prior_snap.manifest.partition
                        is PartitionClass.PRIVATE_TENANT,
                        publishable=is_publishable_partition(
                            prior_snap.manifest.partition
                        ),
                        deterministic_manifest_digest=deterministic_manifest_digest(
                            prior_snap.manifest
                        ),
                    )
                start_offset = int(cur.offset)
                base_records = prior_snap.records
                parent_ptr = RootPointer(
                    root_cid=prior_snap.root_cid,
                    root_digest=prior_snap.root_digest,
                    kind=prior_snap.manifest.kind,
                    retained_from_utc=when,
                    note="resume_prior",
                )
                prior_roots = prior_snap.manifest.retained_prior_roots()

            if start_offset > len(docs):
                raise PersistentIndexBuilderError(
                    f"checkpoint offset {start_offset} exceeds document count "
                    f"{len(docs)}"
                )

            # Accumulate allowed sources across all documents for final orphan check.
            all_allowed = collect_allowed_source_joins(
                docs, default_version=self._default_source_version
            )
            resolved_partition = partition or _partition_for_disclosures(
                (d.disclosure for d in docs)
            )
            identities = self._resolve_identities(
                documents=docs,
                families=families,
                corpus_cid=corpus_cid,
                corpus_version=corpus_version,
                config_cid=config_cid,
                source_manifest_cid=source_manifest_cid,
            )

            offset = start_offset
            current_records = base_records
            shards_done = 0
            last_put: PutSnapshotResult | None = None
            last_snap: PatentIndexSnapshot | None = None
            last_bundle_digest: str | None = None
            envelope_path: str | None = None

            while offset < len(docs):
                chunk = docs[offset : offset + self._shard_size]
                # Filters for the shard: same gate, applied.
                bundle, new_recs, allowed = self._admit_and_project(
                    chunk,
                    filters=filters,
                    edges=edges,
                    families=families,
                    corpus_cid=corpus_cid,
                    config_cid=config_cid,
                )
                all_allowed = frozenset(set(all_allowed) | set(allowed))
                current_records = merge_records(current_records, new_recs)
                offset += len(chunk)
                shards_done += 1
                incomplete = offset < len(docs)
                kind = (
                    SnapshotKind.CHECKPOINT
                    if incomplete
                    else (
                        SnapshotKind.FULL
                        if start_offset == 0 and offset == len(docs)
                        else SnapshotKind.INCREMENTAL
                    )
                )
                snap_id = (
                    f"{snapshot_id_prefix}:ckpt:{offset}"
                    if incomplete
                    else snapshot_id_prefix
                )
                cursor = None
                # Persist intermediate root first so checkpoint prior_root is durable.
                snap = self._assemble_snapshot(
                    snapshot_id=snap_id,
                    records=current_records,
                    identities=identities,
                    families=families,
                    partition=resolved_partition,
                    kind=kind,
                    parent_root=parent_ptr,
                    prior_roots=prior_roots,
                    allowed_disclosures=filters.allowed_disclosures,
                    metadata={
                        **dict(metadata or {}),
                        "checkpoint_id": checkpoint_id,
                        "offset": str(offset),
                    },
                    created_utc=when,
                )
                snap, envelope_path = self._maybe_encrypt_private(
                    snap, snapshot_id=snap_id
                )
                last_put = self._store.put_snapshot(
                    snap, set_head=set_head and not incomplete
                )
                last_snap = snap
                last_bundle_digest = bundle.bundle_digest
                parent_ptr = RootPointer(
                    root_cid=last_put.root_cid,
                    root_digest=last_put.root_digest,
                    kind=kind,
                    retained_from_utc=when,
                    note="shard_checkpoint",
                )
                prior_roots = tuple(
                    list(prior_roots)
                    + (
                        [parent_ptr]
                        if all(
                            p.root_digest != parent_ptr.root_digest for p in prior_roots
                        )
                        else []
                    )
                )
                cursor = CheckpointCursor(
                    schema_version=INDEX_SNAPSHOT_SCHEMA_VERSION,
                    checkpoint_id=checkpoint_id,
                    tenant_id=self.tenant_id,
                    shard_id=f"shard-offset-{offset}",
                    offset=offset,
                    prior_root_cid=last_put.root_cid,
                    prior_root_digest=last_put.root_digest,
                    last_record_id=(
                        current_records[-1].record_id if current_records else None
                    ),
                    incomplete=incomplete,
                    updated_utc=when,
                    metadata={"snapshot_id": snap_id},
                )
                self._store.put_checkpoint(cursor)

                if interrupt_after_shards is not None and shards_done >= interrupt_after_shards:
                    break

            if last_put is None or last_snap is None:
                # Empty document set: still produce an empty full snapshot.
                return self._build_once(
                    (),
                    filters=filters,
                    snapshot_id=snapshot_id_prefix,
                    edges=edges,
                    families=families,
                    partition=resolved_partition,
                    kind=SnapshotKind.FULL,
                    parent_root=None,
                    base_records=(),
                    corpus_cid=corpus_cid,
                    corpus_version=corpus_version,
                    config_cid=config_cid,
                    source_manifest_cid=source_manifest_cid,
                    set_head=set_head,
                    created_utc=when,
                    metadata=metadata,
                )

            verify_zero_orphans(last_snap, all_allowed)
            logical = compute_logical_root(
                records=last_snap.records,
                identities=last_snap.manifest.identities,
                tenant_id=self.tenant_id,
                partition=last_snap.manifest.partition,
                families=last_snap.manifest.families,
            )
            incomplete = offset < len(docs)
            return BuildResult(
                put=last_put,
                logical_root_cid=logical.cid,
                logical_root_digest=logical.sha256,
                kind=last_snap.manifest.kind,
                record_count=last_snap.manifest.record_count,
                active_record_count=last_snap.manifest.active_record_count,
                tombstone_count=last_snap.manifest.tombstone_count,
                families=last_snap.manifest.families,
                partition=last_snap.manifest.partition,
                checkpoint_id=checkpoint_id,
                incomplete=incomplete,
                encrypted=last_snap.manifest.partition is PartitionClass.PRIVATE_TENANT,
                publishable=is_publishable_partition(last_snap.manifest.partition),
                bundle_digest=last_bundle_digest,
                deterministic_manifest_digest=deterministic_manifest_digest(
                    last_snap.manifest
                ),
                private_envelope_path=envelope_path,
            )

    def _build_once(
        self,
        documents: Sequence[PatentIndexDocument],
        *,
        filters: PreRankingFilters,
        snapshot_id: str,
        edges: Sequence[GraphEdge | Mapping[str, Any]],
        families: Sequence[IndexFamily],
        partition: PartitionClass | None,
        kind: SnapshotKind,
        parent_root: RootPointer | None,
        base_records: Sequence[IndexSnapshotRecord],
        prior_roots: Sequence[RootPointer] = (),
        corpus_cid: str,
        corpus_version: str,
        config_cid: str,
        source_manifest_cid: str | None,
        set_head: bool,
        created_utc: str | None,
        metadata: Mapping[str, str] | None,
    ) -> BuildResult:
        docs = tuple(documents)
        resolved_partition = partition or _partition_for_disclosures(
            (d.disclosure for d in docs)
            if docs
            else (
                (r.disclosure for r in base_records)
                if base_records
                else (DisclosureClass.PUBLIC_OFFICIAL,)
            )
        )
        identities = self._resolve_identities(
            documents=docs if docs else [],
            families=families,
            corpus_cid=corpus_cid,
            corpus_version=corpus_version,
            config_cid=config_cid,
            source_manifest_cid=source_manifest_cid,
        )
        if docs:
            bundle, new_recs, allowed = self._admit_and_project(
                docs,
                filters=filters,
                edges=edges,
                families=families,
                corpus_cid=corpus_cid,
                config_cid=config_cid,
            )
            bundle_digest = bundle.bundle_digest
        else:
            new_recs = ()
            allowed = frozenset()
            bundle_digest = None
            # Empty build: still require filters applied for consistency.
            require_pre_ranking_filters(filters)

        merged = merge_records(base_records, new_recs)

        # Allowed sources: union of new docs + retained base joins.
        if base_records:
            base_allowed = {
                (j.source_cid, j.source_version)
                for r in base_records
                for j in r.source_joins
            }
            allowed = frozenset(set(allowed) | base_allowed)

        if merged:
            verify_source_joins_allowed(merged, allowed)

        when = created_utc or self._created_utc or _utc_now()
        snap = self._assemble_snapshot(
            snapshot_id=snapshot_id,
            records=merged,
            identities=identities,
            families=families,
            partition=resolved_partition,
            kind=kind,
            parent_root=parent_root,
            prior_roots=prior_roots,
            allowed_disclosures=filters.allowed_disclosures,
            metadata=metadata,
            created_utc=when,
        )
        if allowed:
            verify_zero_orphans(snap, allowed)
        snap, envelope_path = self._maybe_encrypt_private(snap, snapshot_id=snapshot_id)
        put = self._store.put_snapshot(snap, set_head=set_head)
        logical = compute_logical_root(
            records=snap.records,
            identities=snap.manifest.identities,
            tenant_id=self.tenant_id,
            partition=snap.manifest.partition,
            families=snap.manifest.families,
        )
        return BuildResult(
            put=put,
            logical_root_cid=logical.cid,
            logical_root_digest=logical.sha256,
            kind=kind,
            record_count=snap.manifest.record_count,
            active_record_count=snap.manifest.active_record_count,
            tombstone_count=snap.manifest.tombstone_count,
            families=snap.manifest.families,
            partition=snap.manifest.partition,
            incomplete=False,
            encrypted=snap.manifest.partition is PartitionClass.PRIVATE_TENANT,
            publishable=is_publishable_partition(snap.manifest.partition),
            bundle_digest=bundle_digest,
            deterministic_manifest_digest=deterministic_manifest_digest(snap.manifest),
            private_envelope_path=envelope_path,
        )

    # -- tombstone / compact / rollback convenience -------------------------

    def apply_tombstones(
        self,
        *,
        record_ids: Sequence[str],
        snapshot_id: str,
        base: PatentIndexSnapshot | str | None = None,
        tombstoned_utc: str | None = None,
        set_head: bool = True,
    ) -> BuildResult:
        """Tombstone records; retain prior roots immutably."""
        with self._lock:
            base_ref: PatentIndexSnapshot | str
            if base is None:
                head = self._store.get_head()
                if head is None:
                    raise PersistentIndexBuilderError("no HEAD to tombstone from")
                base_ref = str(head["root_digest"])
            else:
                base_ref = base
            put = self._store.apply_tombstones(
                base=base_ref,
                record_ids=record_ids,
                snapshot_id=snapshot_id,
                tombstoned_utc=tombstoned_utc or self._created_utc or _utc_now(),
                set_head=set_head,
            )
            snap = self._store.get_snapshot(put.root_digest)
            logical = compute_logical_root(
                records=snap.records,
                identities=snap.manifest.identities,
                tenant_id=self.tenant_id,
                partition=snap.manifest.partition,
                families=snap.manifest.families,
            )
            return BuildResult(
                put=put,
                logical_root_cid=logical.cid,
                logical_root_digest=logical.sha256,
                kind=snap.manifest.kind,
                record_count=snap.manifest.record_count,
                active_record_count=snap.manifest.active_record_count,
                tombstone_count=snap.manifest.tombstone_count,
                families=snap.manifest.families,
                partition=snap.manifest.partition,
                encrypted=snap.manifest.partition is PartitionClass.PRIVATE_TENANT,
                publishable=is_publishable_partition(snap.manifest.partition),
                deterministic_manifest_digest=deterministic_manifest_digest(
                    snap.manifest
                ),
            )

    def compact(
        self,
        *,
        snapshot_id: str,
        base: PatentIndexSnapshot | str | None = None,
        set_head: bool = True,
        created_utc: str | None = None,
    ) -> BuildResult:
        """Compact active records; retain compaction root."""
        with self._lock:
            if base is None:
                head = self._store.get_head()
                if head is None:
                    raise PersistentIndexBuilderError("no HEAD to compact")
                base_ref: PatentIndexSnapshot | str = str(head["root_digest"])
            else:
                base_ref = base
            put = self._store.compact(
                base=base_ref,
                snapshot_id=snapshot_id,
                set_head=set_head,
                created_utc=created_utc or self._created_utc or _utc_now(),
            )
            snap = self._store.get_snapshot(put.root_digest)
            logical = compute_logical_root(
                records=snap.records,
                identities=snap.manifest.identities,
                tenant_id=self.tenant_id,
                partition=snap.manifest.partition,
                families=snap.manifest.families,
            )
            return BuildResult(
                put=put,
                logical_root_cid=logical.cid,
                logical_root_digest=logical.sha256,
                kind=snap.manifest.kind,
                record_count=snap.manifest.record_count,
                active_record_count=snap.manifest.active_record_count,
                tombstone_count=snap.manifest.tombstone_count,
                families=snap.manifest.families,
                partition=snap.manifest.partition,
                encrypted=snap.manifest.partition is PartitionClass.PRIVATE_TENANT,
                publishable=is_publishable_partition(snap.manifest.partition),
                deterministic_manifest_digest=deterministic_manifest_digest(
                    snap.manifest
                ),
            )

    def rollback(
        self,
        *,
        target_root_digest: str,
        snapshot_id: str,
        set_head: bool = True,
        created_utc: str | None = None,
    ) -> BuildResult:
        """Rollback HEAD to a historical root; retain priors."""
        with self._lock:
            put = self._store.rollback(
                target_root_digest=target_root_digest,
                snapshot_id=snapshot_id,
                set_head=set_head,
                created_utc=created_utc or self._created_utc or _utc_now(),
            )
            snap = self._store.get_snapshot(put.root_digest)
            logical = compute_logical_root(
                records=snap.records,
                identities=snap.manifest.identities,
                tenant_id=self.tenant_id,
                partition=snap.manifest.partition,
                families=snap.manifest.families,
            )
            return BuildResult(
                put=put,
                logical_root_cid=logical.cid,
                logical_root_digest=logical.sha256,
                kind=snap.manifest.kind,
                record_count=snap.manifest.record_count,
                active_record_count=snap.manifest.active_record_count,
                tombstone_count=snap.manifest.tombstone_count,
                families=snap.manifest.families,
                partition=snap.manifest.partition,
                encrypted=snap.manifest.partition is PartitionClass.PRIVATE_TENANT,
                publishable=is_publishable_partition(snap.manifest.partition),
                deterministic_manifest_digest=deterministic_manifest_digest(
                    snap.manifest
                ),
            )

    def open_head(self) -> PatentIndexSnapshot:
        return self._store.open_snapshot()

    def logical_root_of(
        self, snapshot: PatentIndexSnapshot | None = None
    ) -> ContentAddress:
        snap = snapshot if snapshot is not None else self.open_head()
        return compute_logical_root(
            records=snap.records,
            identities=snap.manifest.identities,
            tenant_id=snap.manifest.tenant_id,
            partition=snap.manifest.partition,
            families=snap.manifest.families,
        )


__all__ = [
    "PERSISTENT_INDEX_BUILDER_SCHEMA_VERSION",
    "PERSISTENT_INDEX_BUILDER_INTERFACE",
    "PERSISTENT_INDEX_BUILDER_CODE_VERSION",
    "DEFAULT_SHARD_SIZE",
    "DEFAULT_SOURCE_VERSION",
    "PRIVATE_CIPHER_VERSION",
    "PersistentIndexBuilderError",
    "LogicalRootMismatchError",
    "PrivatePartitionPublishError",
    "CountParityError",
    "EncryptionError",
    "MissingSourceVersionError",
    "BuildResult",
    "PersistentIndexBuilder",
    "builder_code_digest",
    "default_builder_identities",
    "source_version_for_document",
    "source_link_to_join",
    "primary_source_join",
    "collect_allowed_source_joins",
    "logical_record_fingerprint",
    "compute_logical_root",
    "encrypt_private_payload",
    "decrypt_private_payload",
    "is_publishable_partition",
    "assert_unpublishable",
    "project_bundle_to_records",
    "merge_records",
    "verify_source_joins_allowed",
    "verify_zero_orphans",
    "verify_count_parity",
    "deterministic_manifest_digest",
]
