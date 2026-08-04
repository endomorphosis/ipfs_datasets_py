"""Production vector index snapshot for the public legal corpus (PATLAW-172).

Builds durable, content-addressed vector index artifacts from a rights-reviewed
public patent-law / regulations corpus materialization (PATLAW-170) using the
pinned local embedding runtime (PATLAW-145).

Design invariants
-----------------
* Every snapshot binds the embedding **model pin** and the corpus **root**
  (``corpus_root_cid`` + ``corpus_digest_sha256``).
* Private, mixed, unknown, or unreviewed text fails **closed** before any
  embedding call or filesystem staging.
* Rebuilds under fixed model + corpus pins are content-address stable
  (identical index digests and vector digests).
* No remote embedding APIs and no Hub upload; default mode is dry-run.
* Explicit ``stage=True`` writes local artifacts only.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
import json
import os
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final, Union

from .embedding_runtime import (
    EMBEDDING_RUNTIME_SCHEMA_VERSION,
    PINNED_BACKEND,
    PINNED_CONFIG_CID,
    PINNED_DIMENSION,
    PINNED_MODEL_CID,
    PINNED_MODEL_ID,
    PINNED_MODEL_REVISION,
    PINNED_PROVIDER,
    VECTOR_STABILITY_TOLERANCE,
    EmbeddingBatchResult,
    LocalEmbeddingRuntime,
    PinnedRuntimeIdentity,
    pinned_runtime_identity,
    vector_content_digest,
    vectors_within_tolerance,
)
from .index_snapshot_contracts import (
    INDEX_SNAPSHOT_SCHEMA_VERSION,
    CodeIdentity,
    ConfigIdentity,
    CorpusIdentity,
    IndexFamily,
    IndexSnapshotManifest,
    IndexSnapshotRecord,
    ModelIdentity,
    PartitionClass,
    PatentIndexSnapshot,
    RecordOp,
    SnapshotIdentityBundle,
    SnapshotKind,
    SourceJoin,
    assert_known_model_pin,
    canonical_json as snapshot_canonical_json,
)
from .public_legal_corpus_materializer import (
    PrivateOrMixedInputError as CorpusPrivateOrMixedInputError,
    PublicLegalCorpusError,
    PublicLegalCorpusMaterialization,
    PublicLegalCorpusMaterializer,
    PublicLegalDocument,
    assert_public_only_documents,
    build_default_public_legal_recipe,
    content_cid_of,
    content_digest_of,
    canonical_json,
)
from .release_policy import (
    PRIVATE_CLASSIFICATIONS,
    PUBLIC_CLASSIFICATIONS,
    is_private_classification,
)
from .retrieval_contracts import (
    DisclosureClass,
    SourceSpan,
    is_private_disclosure,
)

# ---------------------------------------------------------------------------
# Schema / interface pins
# ---------------------------------------------------------------------------

SCHEMA_VERSION: Final = "patent.public_legal_vector.v1"
INTERFACE: Final = "PublicLegalVectorBuilder@1"
PRODUCER: Final = "producer:public-legal-vector-builder"
CONFIG_ID: Final = "config:public-legal-vector/v1"
TASK_ID: Final = "PATLAW-172"
GOAL_ID: Final = "PATLAW-G211"
CODE_VERSION: Final = "1.0.0"

# Known model pin token required by index snapshot contracts.
DEFAULT_MODEL_PIN: Final = "local-hashed-term-projection@1.0.0"

MANIFEST_FILENAME: Final = "public-legal-vector.manifest.json"
VECTORS_FILENAME: Final = "vectors.jsonl"
VECTOR_ROOT_FILENAME: Final = "vector-root.json"
SNAPSHOT_FILENAME: Final = "vector-snapshot.json"
EMBEDDING_RECEIPT_FILENAME: Final = "embedding-receipt.json"

DEFAULT_TENANT_ID: Final = "public-legal"
DEFAULT_CREATED_UTC: Final = "2026-08-01T00:00:00Z"

PathLike = Union[str, Path]
JsonMapping = Mapping[str, Any]

PUBLIC_CLASSIFICATION_SET: Final[frozenset[str]] = frozenset(PUBLIC_CLASSIFICATIONS)
PRIVATE_CLASSIFICATION_SET: Final[frozenset[str]] = frozenset(PRIVATE_CLASSIFICATIONS)

_FILE_MODE: Final = 0o600
_DIR_MODE: Final = 0o700

# Wall-clock / path fields excluded from content digests.
_NON_CONTENT_MANIFEST_KEYS: Final[frozenset[str]] = frozenset(
    {
        "created_utc",
        "notes",
        "output_dir",
        "staged_at_utc",
    }
)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class PublicLegalVectorError(ValueError):
    """Base error for public legal vector index builds."""

    code: str = "public_legal_vector_error"

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        if code is not None:
            self.code = code

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "kind": "error", "message": str(self)}


class PrivateTextRejectedError(PublicLegalVectorError):
    """Raised when private, mixed, or unknown text is offered for embedding."""

    code = "private_text_rejected"


class ModelPinError(PublicLegalVectorError):
    """Raised when the embedding model pin is missing or unknown."""

    code = "model_pin_error"


class CorpusRootError(PublicLegalVectorError):
    """Raised when the corpus root pin is missing or inconsistent."""

    code = "corpus_root_error"


class VectorIntegrityError(PublicLegalVectorError):
    """Raised when vector digests, counts, or rebuild stability fail."""

    code = "vector_integrity"


class SchemaValidationError(PublicLegalVectorError):
    """Raised when a row or manifest fails structural validation."""

    code = "schema_validation"


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class BuildMode(str, Enum):
    """How the vector build is executed."""

    DRY_RUN = "dry_run"
    STAGE = "stage"


# ---------------------------------------------------------------------------
# I/O helpers
# ---------------------------------------------------------------------------


def _ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(path, _DIR_MODE)
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


def _atomic_write_text(path: Path, text: str) -> None:
    _atomic_write_bytes(path, text.encode("utf-8"))


def builder_code_digest() -> str:
    """Stable digest of this builder revision (no wall-clock input)."""
    return content_digest_of(
        {
            "code_version": CODE_VERSION,
            "interface": INTERFACE,
            "schema_version": SCHEMA_VERSION,
            "snapshot_schema": INDEX_SNAPSHOT_SCHEMA_VERSION,
            "embedding_runtime_schema": EMBEDDING_RUNTIME_SCHEMA_VERSION,
            "model_pin": DEFAULT_MODEL_PIN,
            "dimension": PINNED_DIMENSION,
        }
    )


# ---------------------------------------------------------------------------
# Model pin binding
# ---------------------------------------------------------------------------


def model_identity_from_runtime(
    identity: PinnedRuntimeIdentity | None = None,
    *,
    model_pin: str = DEFAULT_MODEL_PIN,
) -> ModelIdentity:
    """Project the pinned local embedding runtime into a snapshot ModelIdentity.

    The *model_pin* token is the contract-layer identity required by index
    snapshot manifests; dimension / model_id / config come from the runtime pin
    so vector rows and the manifest agree on the actual embedding space.
    """
    pin = identity or pinned_runtime_identity()
    try:
        assert_known_model_pin(model_pin)
    except Exception as exc:  # pragma: no cover - defensive
        raise ModelPinError(f"unknown model pin {model_pin!r}: {exc}") from exc
    return ModelIdentity(
        model_pin=model_pin,
        provider="local" if pin.provider in {"local", PINNED_PROVIDER, "local_hash"} else pin.provider,
        model_id=pin.model_id or PINNED_MODEL_ID,
        model_version=pin.model_revision or PINNED_MODEL_REVISION,
        dimension=int(pin.dimension or PINNED_DIMENSION),
        config_cid=pin.config_cid or PINNED_CONFIG_CID,
        model_cid=pin.model_cid or PINNED_MODEL_CID,
        backend=pin.backend or PINNED_BACKEND,
    )


def default_model_identity() -> ModelIdentity:
    """Return the production model pin bound to the local embedding runtime."""
    return model_identity_from_runtime(pinned_runtime_identity())


# ---------------------------------------------------------------------------
# Classification / privacy gates
# ---------------------------------------------------------------------------


def _coerce_disclosure(classification: str | DisclosureClass) -> DisclosureClass:
    if isinstance(classification, DisclosureClass):
        return classification
    text = str(classification or "").strip().lower().replace("-", "_")
    try:
        return DisclosureClass(text)
    except ValueError as exc:
        raise PrivateTextRejectedError(
            f"unknown disclosure/classification {classification!r} fails closed"
        ) from exc


def assert_public_only_for_vector(
    documents: Sequence[PublicLegalDocument | Mapping[str, Any]],
) -> tuple[PublicLegalDocument, ...]:
    """Fail closed if any document is private, mixed, or unknown.

    Re-admits raw mappings through :class:`PublicLegalDocument` so classification
    gates from PATLAW-170 apply before any embedding work begins.
    """
    if not documents:
        raise SchemaValidationError("at least one document is required for vector build")

    admitted: list[PublicLegalDocument] = []
    for index, item in enumerate(documents):
        if isinstance(item, PublicLegalDocument):
            doc = item
        elif isinstance(item, Mapping):
            raw_class = str(item.get("classification") or "public_official")
            try:
                disclosure = _coerce_disclosure(raw_class)
            except PrivateTextRejectedError:
                raise
            if (
                disclosure is DisclosureClass.UNKNOWN
                or is_private_disclosure(disclosure)
                or raw_class in PRIVATE_CLASSIFICATION_SET
                or is_private_classification(raw_class)
                or raw_class not in PUBLIC_CLASSIFICATION_SET
            ):
                raise PrivateTextRejectedError(
                    f"documents[{index}] classification {raw_class!r} cannot enter "
                    "the public legal vector index"
                )
            try:
                doc = PublicLegalDocument.from_dict(item)
            except CorpusPrivateOrMixedInputError as exc:
                raise PrivateTextRejectedError(str(exc)) from exc
            except PublicLegalCorpusError as exc:
                # Unreviewed rights / schema issues still fail closed.
                if "private" in str(exc).lower() or "mixed" in str(exc).lower():
                    raise PrivateTextRejectedError(str(exc)) from exc
                raise SchemaValidationError(
                    f"documents[{index}] is invalid: {exc}"
                ) from exc
        else:
            raise SchemaValidationError(
                f"documents[{index}] must be PublicLegalDocument or mapping"
            )

        if (
            doc.classification not in PUBLIC_CLASSIFICATION_SET
            or is_private_classification(doc.classification)
            or is_private_disclosure(doc.classification)
        ):
            raise PrivateTextRejectedError(
                f"document {doc.record_id!r} classification "
                f"{doc.classification!r} cannot enter the public legal vector index"
            )
        admitted.append(doc)

    try:
        assert_public_only_documents(admitted)
    except CorpusPrivateOrMixedInputError as exc:
        raise PrivateTextRejectedError(str(exc)) from exc

    # Stable order for content addressing.
    return tuple(sorted(admitted, key=lambda d: d.record_id))


# ---------------------------------------------------------------------------
# Row / manifest records
# ---------------------------------------------------------------------------


def _embedding_text(document: PublicLegalDocument) -> str:
    """Canonical text projection for embedding (title + citation + body)."""
    parts = [
        str(document.title or "").strip(),
        str(document.citation or "").strip(),
        str(document.text or "").strip(),
    ]
    return "\n".join(p for p in parts if p)


def _source_join_for_document(document: PublicLegalDocument) -> SourceJoin:
    version = (
        str(document.source_lineage.source_revision or "").strip()
        or str(document.current_through or "").strip()
        or "v1"
    )
    return SourceJoin(
        source_cid=document.source_cid,
        source_version=version,
        artifact_id=document.record_id,
        span=SourceSpan(start=0, end=min(len(document.text), 1_000_000)),
        source_receipt_id=f"receipt:{document.source_root_id}",
        authority_tier="official-base",
    )


@dataclass(frozen=True, slots=True)
class PublicLegalVectorRow:
    """One content-addressed vector mapping for a public legal document."""

    document_id: str
    record_id: str
    family: str
    classification: str
    source_cid: str
    document_cid: str
    source_root_id: str
    source_version: str
    vector_digest: str
    dimension: int
    model_pin: str
    input_digest: str
    vector: tuple[float, ...] = ()
    citation: str = ""
    title: str = ""
    metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.document_id or not self.record_id:
            raise SchemaValidationError("document_id and record_id are required")
        if self.dimension < 1:
            raise SchemaValidationError("dimension must be >= 1")
        if len(self.vector_digest) != 64:
            raise SchemaValidationError("vector_digest must be a 64-char hex digest")
        if self.vector and len(self.vector) != self.dimension:
            raise VectorIntegrityError(
                f"vector length {len(self.vector)} != dimension {self.dimension}"
            )
        object.__setattr__(
            self, "metadata", MappingProxyType(dict(self.metadata or {}))
        )

    def to_dict(self, *, include_vector: bool = True) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "citation": self.citation,
            "classification": self.classification,
            "dimension": self.dimension,
            "document_cid": self.document_cid,
            "document_id": self.document_id,
            "family": self.family,
            "input_digest": self.input_digest,
            "metadata": dict(self.metadata),
            "model_pin": self.model_pin,
            "record_id": self.record_id,
            "source_cid": self.source_cid,
            "source_root_id": self.source_root_id,
            "source_version": self.source_version,
            "title": self.title,
            "vector_digest": self.vector_digest,
        }
        if include_vector and self.vector:
            payload["vector"] = [float(x) for x in self.vector]
        return payload

    def content_payload(self) -> dict[str, Any]:
        """Payload used for content addressing (excludes raw float vector)."""
        return {
            "classification": self.classification,
            "dimension": self.dimension,
            "document_cid": self.document_cid,
            "document_id": self.document_id,
            "family": self.family,
            "input_digest": self.input_digest,
            "model_pin": self.model_pin,
            "record_id": self.record_id,
            "source_cid": self.source_cid,
            "source_root_id": self.source_root_id,
            "source_version": self.source_version,
            "vector_digest": self.vector_digest,
        }


@dataclass(frozen=True, slots=True)
class PublicLegalVectorManifest:
    """Content-addressed vector index manifest binding model pin and corpus root."""

    schema_version: str
    interface: str
    task_id: str
    goal_id: str
    producer: str
    config_id: str
    code_version: str
    partition: str
    index_root_cid: str
    index_digest_sha256: str
    corpus_root_cid: str
    corpus_digest_sha256: str
    model_pin: str
    model: Mapping[str, Any]
    dimension: int
    document_count: int
    vector_count: int
    tenant_id: str
    families: tuple[str, ...]
    document_joins: tuple[Mapping[str, Any], ...]
    embedding_receipt: Mapping[str, Any]
    code_digest: str
    mode: str = BuildMode.DRY_RUN.value
    created_utc: str = DEFAULT_CREATED_UTC
    notes: str = ""
    snapshot_root_cid: str = ""
    snapshot_root_digest: str = ""

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_VERSION:
            raise SchemaValidationError(
                f"schema_version must be {SCHEMA_VERSION!r}, got {self.schema_version!r}"
            )
        if self.partition != "public":
            raise PrivateTextRejectedError(
                f"vector manifest partition must be 'public', got {self.partition!r}"
            )
        if self.document_count != self.vector_count:
            raise VectorIntegrityError(
                f"document_count {self.document_count} != vector_count {self.vector_count}"
            )
        try:
            assert_known_model_pin(self.model_pin)
        except Exception as exc:
            raise ModelPinError(str(exc)) from exc
        if not self.corpus_root_cid or not self.corpus_digest_sha256:
            raise CorpusRootError("manifest requires corpus_root_cid and corpus_digest")
        if not self.index_root_cid or not self.index_digest_sha256:
            raise VectorIntegrityError("manifest requires index root cid and digest")
        object.__setattr__(self, "model", MappingProxyType(dict(self.model or {})))
        object.__setattr__(
            self,
            "embedding_receipt",
            MappingProxyType(dict(self.embedding_receipt or {})),
        )
        object.__setattr__(
            self,
            "document_joins",
            tuple(dict(j) for j in (self.document_joins or ())),
        )
        object.__setattr__(
            self,
            "families",
            tuple(self.families or (IndexFamily.VECTOR.value,)),
        )

    def _content_body(self) -> dict[str, Any]:
        return _manifest_content_body(
            code_digest=self.code_digest,
            code_version=self.code_version,
            config_id=self.config_id,
            corpus_digest_sha256=self.corpus_digest_sha256,
            corpus_root_cid=self.corpus_root_cid,
            dimension=self.dimension,
            document_count=self.document_count,
            document_joins=self.document_joins,
            embedding_receipt=dict(self.embedding_receipt),
            families=self.families,
            goal_id=self.goal_id,
            interface=self.interface,
            model=dict(self.model),
            model_pin=self.model_pin,
            partition=self.partition,
            producer=self.producer,
            schema_version=self.schema_version,
            task_id=self.task_id,
            tenant_id=self.tenant_id,
            vector_count=self.vector_count,
        )

    def compute_index_digest(self) -> str:
        return content_digest_of(self._content_body())

    def compute_index_cid(self) -> str:
        return content_cid_of(self._content_body())

    def to_dict(self) -> dict[str, Any]:
        return {
            "code_digest": self.code_digest,
            "code_version": self.code_version,
            "config_id": self.config_id,
            "corpus_digest_sha256": self.corpus_digest_sha256,
            "corpus_root_cid": self.corpus_root_cid,
            "created_utc": self.created_utc,
            "dimension": self.dimension,
            "document_count": self.document_count,
            "document_joins": [dict(j) for j in self.document_joins],
            "embedding_receipt": dict(self.embedding_receipt),
            "families": list(self.families),
            "goal_id": self.goal_id,
            "index_digest_sha256": self.index_digest_sha256,
            "index_root_cid": self.index_root_cid,
            "interface": self.interface,
            "mode": self.mode,
            "model": dict(self.model),
            "model_pin": self.model_pin,
            "notes": self.notes,
            "partition": self.partition,
            "producer": self.producer,
            "schema_version": self.schema_version,
            "snapshot_root_cid": self.snapshot_root_cid,
            "snapshot_root_digest": self.snapshot_root_digest,
            "task_id": self.task_id,
            "tenant_id": self.tenant_id,
            "vector_count": self.vector_count,
        }

    def to_canonical_json(self) -> str:
        return canonical_json(self.to_dict())

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "PublicLegalVectorManifest":
        if not isinstance(value, Mapping):
            raise SchemaValidationError("manifest must be a mapping")
        return cls(
            schema_version=str(value.get("schema_version") or SCHEMA_VERSION),
            interface=str(value.get("interface") or INTERFACE),
            task_id=str(value.get("task_id") or TASK_ID),
            goal_id=str(value.get("goal_id") or GOAL_ID),
            producer=str(value.get("producer") or PRODUCER),
            config_id=str(value.get("config_id") or CONFIG_ID),
            code_version=str(value.get("code_version") or CODE_VERSION),
            partition=str(value.get("partition") or "public"),
            index_root_cid=str(value.get("index_root_cid") or ""),
            index_digest_sha256=str(value.get("index_digest_sha256") or ""),
            corpus_root_cid=str(value.get("corpus_root_cid") or ""),
            corpus_digest_sha256=str(value.get("corpus_digest_sha256") or ""),
            model_pin=str(value.get("model_pin") or ""),
            model=dict(value.get("model") or {}),
            dimension=int(value.get("dimension") or 0),
            document_count=int(value.get("document_count") or 0),
            vector_count=int(value.get("vector_count") or 0),
            tenant_id=str(value.get("tenant_id") or DEFAULT_TENANT_ID),
            families=tuple(value.get("families") or (IndexFamily.VECTOR.value,)),
            document_joins=tuple(value.get("document_joins") or ()),
            embedding_receipt=dict(value.get("embedding_receipt") or {}),
            code_digest=str(value.get("code_digest") or ""),
            mode=str(value.get("mode") or BuildMode.DRY_RUN.value),
            created_utc=str(value.get("created_utc") or DEFAULT_CREATED_UTC),
            notes=str(value.get("notes") or ""),
            snapshot_root_cid=str(value.get("snapshot_root_cid") or ""),
            snapshot_root_digest=str(value.get("snapshot_root_digest") or ""),
        )


# Receipt fields that may vary across identical embeddings (cache, wall-clock).
_NON_CONTENT_RECEIPT_KEYS: Final[frozenset[str]] = frozenset(
    {
        "cache_hits",
        "cache_misses",
        "elapsed_ms",
        "device_fallback_applied",
        "device_requested",
        "device_selected",
    }
)


def _stable_embedding_receipt(receipt: Mapping[str, Any]) -> dict[str, Any]:
    """Project an embedding receipt into content-stable fields only."""
    raw = dict(receipt or {})
    # Prefer an explicit allow-list so new receipt diagnostics cannot drift CIDs.
    identity = dict(raw.get("identity") or {})
    policy = dict(raw.get("policy") or {})
    return {
        "batch_size": raw.get("batch_size"),
        "identity": {
            "backend": identity.get("backend"),
            "code_digest": identity.get("code_digest"),
            "code_version": identity.get("code_version"),
            "config_cid": identity.get("config_cid"),
            "config_digest": identity.get("config_digest"),
            "dimension": identity.get("dimension"),
            "model_cid": identity.get("model_cid"),
            "model_id": identity.get("model_id"),
            "model_revision": identity.get("model_revision"),
            "normalize": identity.get("normalize"),
            "provider": identity.get("provider"),
            "schema_version": identity.get("schema_version"),
            "tokenizer_id": identity.get("tokenizer_id"),
            "tokenizer_revision": identity.get("tokenizer_revision"),
        },
        "input_digests": list(raw.get("input_digests") or []),
        "policy": {
            "allow_execute": policy.get("allow_execute"),
            "code": policy.get("code"),
            "disclosure": policy.get("disclosure"),
            "private_route": policy.get("private_route"),
            "route": policy.get("route"),
        },
        "schema_version": raw.get("schema_version"),
        "stability_tolerance": raw.get("stability_tolerance"),
        "text_count": raw.get("text_count"),
        "vector_digest": raw.get("vector_digest"),
    }


def _manifest_content_body(
    *,
    code_digest: str,
    code_version: str,
    config_id: str,
    corpus_digest_sha256: str,
    corpus_root_cid: str,
    dimension: int,
    document_count: int,
    document_joins: Sequence[Mapping[str, Any]],
    embedding_receipt: Mapping[str, Any],
    families: Sequence[str],
    goal_id: str,
    interface: str,
    model: Mapping[str, Any],
    model_pin: str,
    partition: str,
    producer: str,
    schema_version: str,
    task_id: str,
    tenant_id: str,
    vector_count: int,
) -> dict[str, Any]:
    """Stable content body for index digests (excludes wall-clock fields)."""
    return {
        "code_digest": code_digest,
        "code_version": code_version,
        "config_id": config_id,
        "corpus_digest_sha256": corpus_digest_sha256,
        "corpus_root_cid": corpus_root_cid,
        "dimension": dimension,
        "document_count": document_count,
        "document_joins": [dict(j) for j in document_joins],
        "embedding_receipt": _stable_embedding_receipt(embedding_receipt),
        "families": list(families),
        "goal_id": goal_id,
        "interface": interface,
        "model": dict(model),
        "model_pin": model_pin,
        "partition": partition,
        "producer": producer,
        "schema_version": schema_version,
        "task_id": task_id,
        "tenant_id": tenant_id,
        "vector_count": vector_count,
    }


@dataclass(frozen=True, slots=True)
class PublicLegalVectorBuildResult:
    """Outcome of a public legal vector index build."""

    rows: tuple[PublicLegalVectorRow, ...]
    manifest: PublicLegalVectorManifest
    snapshot: PatentIndexSnapshot
    mode: BuildMode
    output_dir: str | None = None
    vectors: tuple[tuple[float, ...], ...] = ()

    @property
    def index_root_cid(self) -> str:
        return self.manifest.index_root_cid

    @property
    def index_digest_sha256(self) -> str:
        return self.manifest.index_digest_sha256

    @property
    def corpus_root_cid(self) -> str:
        return self.manifest.corpus_root_cid

    @property
    def model_pin(self) -> str:
        return self.manifest.model_pin

    @property
    def dimension(self) -> int:
        return self.manifest.dimension

    def to_dict(self, *, include_vectors: bool = False) -> dict[str, Any]:
        return {
            "corpus_root_cid": self.corpus_root_cid,
            "dimension": self.dimension,
            "document_count": len(self.rows),
            "index_digest_sha256": self.index_digest_sha256,
            "index_root_cid": self.index_root_cid,
            "manifest": self.manifest.to_dict(),
            "mode": self.mode.value if isinstance(self.mode, BuildMode) else str(self.mode),
            "model_pin": self.model_pin,
            "output_dir": self.output_dir,
            "rows": [r.to_dict(include_vector=include_vectors) for r in self.rows],
            "snapshot_root_cid": self.manifest.snapshot_root_cid,
            "snapshot_root_digest": self.manifest.snapshot_root_digest,
        }

    def to_canonical_bytes(self) -> bytes:
        """Content-stable bytes (excludes wall-clock and output path)."""
        payload = {
            "manifest": self.manifest._content_body(),
            "manifest_pins": {
                "index_digest_sha256": self.manifest.index_digest_sha256,
                "index_root_cid": self.manifest.index_root_cid,
            },
            "rows": [r.content_payload() for r in self.rows],
        }
        return canonical_json(payload).encode("utf-8")


# ---------------------------------------------------------------------------
# Snapshot assembly
# ---------------------------------------------------------------------------


def _snapshot_identities(
    *,
    corpus_root_cid: str,
    corpus_digest: str,
    source_manifest_cid: str,
    corpus_version: str,
    record_count: int,
    model: ModelIdentity,
    code_digest: str,
) -> SnapshotIdentityBundle:
    config_digest = content_digest_of(
        {
            "builder": INTERFACE,
            "config_id": CONFIG_ID,
            "model_pin": model.model_pin,
            "dimension": model.dimension,
        }
    )
    return SnapshotIdentityBundle(
        schema_version=INDEX_SNAPSHOT_SCHEMA_VERSION,
        corpus=CorpusIdentity(
            corpus_cid=corpus_root_cid,
            corpus_digest=corpus_digest,
            source_manifest_cid=source_manifest_cid,
            corpus_version=corpus_version,
            record_count=record_count,
        ),
        code=CodeIdentity(
            code_version=CODE_VERSION,
            code_digest=code_digest,
            interface=INTERFACE,
        ),
        config=ConfigIdentity(
            config_cid=model.config_cid,
            config_digest=config_digest,
            field_weights_config_cid=model.config_cid,
        ),
        model=model,
    )


def _build_snapshot_records(
    rows: Sequence[PublicLegalVectorRow],
    *,
    tenant_id: str,
) -> tuple[IndexSnapshotRecord, ...]:
    out: list[IndexSnapshotRecord] = []
    for row in rows:
        join = SourceJoin(
            source_cid=row.source_cid,
            source_version=row.source_version,
            artifact_id=row.record_id,
            span=SourceSpan(start=0, end=1),
            source_receipt_id=f"receipt:{row.source_root_id}",
            authority_tier="official-base",
        )
        payload = {
            "family": IndexFamily.VECTOR.value,
            "model_pin": row.model_pin,
            "row_id": f"vector:doc:{row.document_id}",
            "vector_digest": row.vector_digest,
            "dimension": row.dimension,
            "document_cid": row.document_cid,
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
                record_id=f"vector:doc:{row.document_id}",
                document_id=row.document_id,
                family=IndexFamily.VECTOR,
                op=RecordOp.UPSERT,
                source_joins=(join,),
                disclosure=_coerce_disclosure(row.classification),
                tenant_id=tenant_id,
                content_digest=content,
                payload_digest=payload_digest,
                metadata={
                    "projector": "public_legal_vector",
                    "vector_digest": row.vector_digest,
                    "model_pin": row.model_pin,
                    "dimension": str(row.dimension),
                },
            )
        )
    out.sort(key=lambda r: (r.record_id, r.content_digest))
    return tuple(out)


def assemble_vector_snapshot(
    rows: Sequence[PublicLegalVectorRow],
    *,
    identities: SnapshotIdentityBundle,
    tenant_id: str = DEFAULT_TENANT_ID,
    snapshot_id: str = "snap:public-legal-vector",
    created_utc: str = DEFAULT_CREATED_UTC,
) -> PatentIndexSnapshot:
    """Assemble a :class:`PatentIndexSnapshot` for the vector family."""
    records = _build_snapshot_records(rows, tenant_id=tenant_id)
    identities.require_model_for_family(IndexFamily.VECTOR)
    # Refresh record_count to active upserts.
    corpus = identities.corpus
    identities = SnapshotIdentityBundle(
        schema_version=identities.schema_version,
        corpus=CorpusIdentity(
            corpus_cid=corpus.corpus_cid,
            corpus_digest=corpus.corpus_digest,
            source_manifest_cid=corpus.source_manifest_cid,
            corpus_version=corpus.corpus_version,
            record_count=len(records),
        ),
        code=identities.code,
        config=identities.config,
        model=identities.model,
    )
    meta = {
        "builder_interface": INTERFACE,
        "builder_schema": SCHEMA_VERSION,
        "publishable": "true",
        "encrypted": "false",
        "task_id": TASK_ID,
        "model_pin": identities.model.model_pin if identities.model else "",
        "corpus_root_cid": corpus.corpus_cid,
    }
    manifest = IndexSnapshotManifest(
        schema_version=INDEX_SNAPSHOT_SCHEMA_VERSION,
        snapshot_id=snapshot_id,
        tenant_id=tenant_id,
        partition=PartitionClass.PUBLIC,
        kind=SnapshotKind.FULL,
        identities=identities,
        families=(IndexFamily.VECTOR,),
        record_count=len(records),
        tombstone_count=0,
        active_record_count=len(records),
        created_utc=created_utc,
        allowed_disclosures=(DisclosureClass.PUBLIC_OFFICIAL,),
        metadata=meta,
    )
    snap = PatentIndexSnapshot(manifest=manifest, records=records)
    snap.verify_source_joins()
    for rec in snap.records:
        if is_private_disclosure(rec.disclosure):
            raise PrivateTextRejectedError(
                f"public vector snapshot contains private record {rec.record_id!r}"
            )
    return snap


# ---------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------


@dataclass
class PublicLegalVectorBuilder:
    """Build a production vector index snapshot for the public legal corpus.

    Parameters
    ----------
    runtime:
        Pinned local embedding runtime. Defaults to the sole production pin.
    tenant_id:
        Tenant label for the public partition (never a private tenant).
    require_all_families:
        When resolving a recipe via the corpus materializer, require every
        source family (strict Hub completeness). Defaults to True for the
        multi-family default fixture.
    """

    runtime: LocalEmbeddingRuntime | None = None
    tenant_id: str = DEFAULT_TENANT_ID
    require_all_families: bool = True
    code_version: str = CODE_VERSION

    def __post_init__(self) -> None:
        self._runtime = self.runtime or LocalEmbeddingRuntime()
        # Re-validate pin equality on construction.
        if self._runtime.identity.to_dict() != pinned_runtime_identity().to_dict():
            raise ModelPinError(
                "embedding runtime identity must equal the sole approved production pin"
            )
        if not self.tenant_id or not str(self.tenant_id).strip():
            raise SchemaValidationError("tenant_id is required")

    @property
    def embedding_runtime(self) -> LocalEmbeddingRuntime:
        return self._runtime

    def build(
        self,
        *,
        corpus: PublicLegalCorpusMaterialization | None = None,
        recipe: Mapping[str, Any] | None = None,
        source_roots: Sequence[Any] | None = None,
        documents: Sequence[PublicLegalDocument | Mapping[str, Any]] | None = None,
        stage: bool = False,
        output_dir: PathLike | None = None,
        created_utc: str = DEFAULT_CREATED_UTC,
        snapshot_id: str = "snap:public-legal-vector",
        notes: str = "",
        include_vectors_in_stage: bool = True,
    ) -> PublicLegalVectorBuildResult:
        """Build the vector index from a corpus materialization or recipe.

        Private inputs raise :class:`PrivateTextRejectedError` before embedding.
        """
        materialization = self._resolve_corpus(
            corpus=corpus,
            recipe=recipe,
            source_roots=source_roots,
            documents=documents,
        )
        return self.build_from_materialization(
            materialization,
            stage=stage,
            output_dir=output_dir,
            created_utc=created_utc,
            snapshot_id=snapshot_id,
            notes=notes,
            include_vectors_in_stage=include_vectors_in_stage,
        )

    def build_from_materialization(
        self,
        materialization: PublicLegalCorpusMaterialization,
        *,
        stage: bool = False,
        output_dir: PathLike | None = None,
        created_utc: str = DEFAULT_CREATED_UTC,
        snapshot_id: str = "snap:public-legal-vector",
        notes: str = "",
        include_vectors_in_stage: bool = True,
    ) -> PublicLegalVectorBuildResult:
        """Build from an already-materialized public legal corpus."""
        if not isinstance(materialization, PublicLegalCorpusMaterialization):
            raise SchemaValidationError(
                "materialization must be PublicLegalCorpusMaterialization"
            )

        # Fail closed: re-admit every document as public-only before embed.
        admitted = assert_public_only_for_vector(materialization.documents)
        if not admitted:
            raise SchemaValidationError("corpus materialization has no documents")

        corpus_root_cid = str(materialization.corpus_root_cid or "").strip()
        corpus_digest = str(materialization.corpus_digest_sha256 or "").strip()
        if not corpus_root_cid or not corpus_digest:
            raise CorpusRootError(
                "corpus materialization is missing corpus_root_cid / corpus_digest"
            )
        if materialization.manifest.partition != "public":
            raise PrivateTextRejectedError(
                f"corpus partition {materialization.manifest.partition!r} is not public"
            )

        model = model_identity_from_runtime(self._runtime.identity)
        model_pin = model.model_pin
        dimension = int(model.dimension)

        # Embed all admitted public texts with the pinned local runtime.
        texts = [_embedding_text(doc) for doc in admitted]
        # use_cache=False keeps receipt digests independent of prior calls;
        # vectors remain exact under the hashed backend regardless of cache.
        batch = self._runtime.embed(
            texts,
            disclosure=DisclosureClass.PUBLIC_OFFICIAL,
            private_route=False,
            remote_requested=False,
            use_cache=False,
        )
        if len(batch.vectors) != len(admitted):
            raise VectorIntegrityError(
                f"embedding returned {len(batch.vectors)} vectors for "
                f"{len(admitted)} documents"
            )
        if batch.identity.dimension != dimension:
            raise ModelPinError(
                f"runtime dimension {batch.identity.dimension} != model pin "
                f"dimension {dimension}"
            )

        rows = self._project_rows(
            admitted,
            vectors=batch.vectors,
            model_pin=model_pin,
            dimension=dimension,
            batch=batch,
        )

        source_manifest_cid = str(
            materialization.manifest.builder_bindings.get("source_manifest_cid")
            or corpus_root_cid
        )
        code_digest = builder_code_digest()
        identities = _snapshot_identities(
            corpus_root_cid=corpus_root_cid,
            corpus_digest=corpus_digest,
            source_manifest_cid=source_manifest_cid,
            corpus_version=f"corpus:{corpus_digest[:16]}",
            record_count=len(rows),
            model=model,
            code_digest=code_digest,
        )
        snapshot = assemble_vector_snapshot(
            rows,
            identities=identities,
            tenant_id=self.tenant_id,
            snapshot_id=snapshot_id,
            created_utc=created_utc,
        )

        joins = tuple(
            {
                "document_cid": row.document_cid,
                "document_id": row.document_id,
                "record_id": row.record_id,
                "source_cid": row.source_cid,
                "source_root_id": row.source_root_id,
                "source_version": row.source_version,
                "vector_digest": row.vector_digest,
            }
            for row in rows
        )
        # Content-stable receipt projection (cache/elapsed stripped from digests).
        receipt_full = dict(batch.receipt.to_dict())
        receipt_stable = _stable_embedding_receipt(receipt_full)

        content_body = _manifest_content_body(
            code_digest=code_digest,
            code_version=self.code_version,
            config_id=CONFIG_ID,
            corpus_digest_sha256=corpus_digest,
            corpus_root_cid=corpus_root_cid,
            dimension=dimension,
            document_count=len(rows),
            document_joins=joins,
            embedding_receipt=receipt_stable,
            families=(IndexFamily.VECTOR.value,),
            goal_id=GOAL_ID,
            interface=INTERFACE,
            model=model.to_dict(),
            model_pin=model_pin,
            partition="public",
            producer=PRODUCER,
            schema_version=SCHEMA_VERSION,
            task_id=TASK_ID,
            tenant_id=self.tenant_id,
            vector_count=len(rows),
        )
        index_digest = content_digest_of(content_body)
        index_cid = content_cid_of(content_body)
        manifest = PublicLegalVectorManifest(
            schema_version=SCHEMA_VERSION,
            interface=INTERFACE,
            task_id=TASK_ID,
            goal_id=GOAL_ID,
            producer=PRODUCER,
            config_id=CONFIG_ID,
            code_version=self.code_version,
            partition="public",
            index_root_cid=index_cid,
            index_digest_sha256=index_digest,
            corpus_root_cid=corpus_root_cid,
            corpus_digest_sha256=corpus_digest,
            model_pin=model_pin,
            model=model.to_dict(),
            dimension=dimension,
            document_count=len(rows),
            vector_count=len(rows),
            tenant_id=self.tenant_id,
            families=(IndexFamily.VECTOR.value,),
            document_joins=joins,
            embedding_receipt=receipt_stable,
            code_digest=code_digest,
            mode=BuildMode.STAGE.value if stage else BuildMode.DRY_RUN.value,
            created_utc=created_utc,
            notes=str(notes or ""),
            snapshot_root_cid=snapshot.root_cid,
            snapshot_root_digest=snapshot.root_digest,
        )
        # Integrity: recomputed digest must match pins.
        if manifest.compute_index_digest() != index_digest:
            raise VectorIntegrityError("index digest pin mismatch after assembly")
        if model_pin != manifest.model_pin:
            raise ModelPinError("model pin drifted during assembly")
        if corpus_root_cid != manifest.corpus_root_cid:
            raise CorpusRootError("corpus root drifted during assembly")
        result = PublicLegalVectorBuildResult(
            rows=rows,
            manifest=manifest,
            snapshot=snapshot,
            mode=BuildMode.STAGE if stage else BuildMode.DRY_RUN,
            output_dir=None,
            vectors=tuple(batch.vectors),
        )

        if stage:
            if output_dir is None:
                raise PublicLegalVectorError(
                    "output_dir is required when stage=True",
                    code="missing_output_dir",
                )
            return self.stage(
                result,
                output_dir=output_dir,
                include_vectors=include_vectors_in_stage,
            )
        return result

    def build_from_default_fixture(
        self,
        *,
        stage: bool = False,
        output_dir: PathLike | None = None,
        created_utc: str = DEFAULT_CREATED_UTC,
        notes: str = "",
    ) -> PublicLegalVectorBuildResult:
        """Build using the compact multi-family public legal CI recipe."""
        recipe = build_default_public_legal_recipe()
        return self.build(
            recipe=recipe,
            stage=stage,
            output_dir=output_dir,
            created_utc=created_utc,
            notes=notes or "PATLAW-172 default public legal vector fixture",
        )

    def stage(
        self,
        result: PublicLegalVectorBuildResult,
        *,
        output_dir: PathLike,
        include_vectors: bool = True,
    ) -> PublicLegalVectorBuildResult:
        """Write vector index artifacts to *output_dir* atomically."""
        # Privacy re-check before any write (classification only; no re-embed).
        for row in result.rows:
            if (
                row.classification not in PUBLIC_CLASSIFICATION_SET
                or is_private_classification(row.classification)
                or is_private_disclosure(row.classification)
            ):
                raise PrivateTextRejectedError(
                    f"row {row.record_id!r} is not public; refusing to stage"
                )
        if result.manifest.partition != "public":
            raise PrivateTextRejectedError(
                "refusing to stage non-public vector partition"
            )
        root = Path(output_dir)
        _ensure_dir(root)

        vectors_lines = [
            canonical_json(row.to_dict(include_vector=include_vectors))
            for row in result.rows
        ]
        vectors_blob = ("\n".join(vectors_lines) + "\n").encode("utf-8")
        vector_root = {
            "corpus_digest_sha256": result.manifest.corpus_digest_sha256,
            "corpus_root_cid": result.manifest.corpus_root_cid,
            "dimension": result.manifest.dimension,
            "document_count": result.manifest.document_count,
            "index_digest_sha256": result.manifest.index_digest_sha256,
            "index_root_cid": result.manifest.index_root_cid,
            "model_pin": result.manifest.model_pin,
            "schema_version": SCHEMA_VERSION,
            "snapshot_root_cid": result.manifest.snapshot_root_cid,
            "snapshot_root_digest": result.manifest.snapshot_root_digest,
            "task_id": TASK_ID,
        }

        _atomic_write_text(
            root / MANIFEST_FILENAME,
            canonical_json(result.manifest.to_dict()) + "\n",
        )
        _atomic_write_bytes(root / VECTORS_FILENAME, vectors_blob)
        _atomic_write_text(
            root / VECTOR_ROOT_FILENAME, canonical_json(vector_root) + "\n"
        )
        _atomic_write_text(
            root / SNAPSHOT_FILENAME,
            snapshot_canonical_json(result.snapshot.to_dict()) + "\n",
        )
        _atomic_write_text(
            root / EMBEDDING_RECEIPT_FILENAME,
            canonical_json(dict(result.manifest.embedding_receipt)) + "\n",
        )

        return PublicLegalVectorBuildResult(
            rows=result.rows,
            manifest=result.manifest,
            snapshot=result.snapshot,
            mode=BuildMode.STAGE,
            output_dir=str(root.resolve()),
            vectors=result.vectors,
        )

    # -- internals ---------------------------------------------------------

    def _resolve_corpus(
        self,
        *,
        corpus: PublicLegalCorpusMaterialization | None,
        recipe: Mapping[str, Any] | None,
        source_roots: Sequence[Any] | None,
        documents: Sequence[PublicLegalDocument | Mapping[str, Any]] | None,
    ) -> PublicLegalCorpusMaterialization:
        if corpus is not None:
            return corpus
        materializer = PublicLegalCorpusMaterializer(
            require_all_families=self.require_all_families
        )
        if recipe is not None:
            try:
                return materializer.materialize_from_recipe(recipe)
            except CorpusPrivateOrMixedInputError as exc:
                raise PrivateTextRejectedError(str(exc)) from exc
        if source_roots is not None and documents is not None:
            try:
                return materializer.materialize(
                    source_roots=source_roots,
                    documents=documents,
                    stage=False,
                )
            except CorpusPrivateOrMixedInputError as exc:
                raise PrivateTextRejectedError(str(exc)) from exc
        raise SchemaValidationError(
            "provide corpus, recipe, or source_roots+documents"
        )

    def _project_rows(
        self,
        documents: Sequence[PublicLegalDocument],
        *,
        vectors: Sequence[Sequence[float]],
        model_pin: str,
        dimension: int,
        batch: EmbeddingBatchResult,
    ) -> tuple[PublicLegalVectorRow, ...]:
        rows: list[PublicLegalVectorRow] = []
        input_digests = list(batch.receipt.input_digests)
        for index, doc in enumerate(documents):
            vec = tuple(float(x) for x in vectors[index])
            if len(vec) != dimension:
                raise VectorIntegrityError(
                    f"document {doc.record_id!r}: vector length "
                    f"{len(vec)} != dimension {dimension}"
                )
            v_digest = vector_content_digest([vec])
            join = _source_join_for_document(doc)
            in_digest = (
                input_digests[index]
                if index < len(input_digests)
                else content_digest_of(_embedding_text(doc))
            )
            rows.append(
                PublicLegalVectorRow(
                    document_id=doc.record_id,
                    record_id=doc.record_id,
                    family=doc.family.value
                    if hasattr(doc.family, "value")
                    else str(doc.family),
                    classification=doc.classification,
                    source_cid=doc.source_cid,
                    document_cid=doc.document_cid,
                    source_root_id=doc.source_root_id,
                    source_version=join.source_version,
                    vector_digest=v_digest,
                    dimension=dimension,
                    model_pin=model_pin,
                    input_digest=in_digest,
                    vector=vec,
                    citation=doc.citation,
                    title=doc.title,
                    metadata={
                        "authority_kind": doc.authority_kind,
                        "source_root_id": doc.source_root_id,
                    },
                )
            )
        rows.sort(key=lambda r: r.document_id)
        return tuple(rows)


# ---------------------------------------------------------------------------
# Module-level convenience API
# ---------------------------------------------------------------------------


def build_public_legal_vector_index(
    *,
    corpus: PublicLegalCorpusMaterialization | None = None,
    recipe: Mapping[str, Any] | None = None,
    stage: bool = False,
    output_dir: PathLike | None = None,
    runtime: LocalEmbeddingRuntime | None = None,
    require_all_families: bool = True,
    created_utc: str = DEFAULT_CREATED_UTC,
    notes: str = "",
) -> PublicLegalVectorBuildResult:
    """Module-level convenience wrapper for :class:`PublicLegalVectorBuilder`."""
    builder = PublicLegalVectorBuilder(
        runtime=runtime,
        require_all_families=require_all_families,
    )
    if corpus is None and recipe is None:
        return builder.build_from_default_fixture(
            stage=stage,
            output_dir=output_dir,
            created_utc=created_utc,
            notes=notes,
        )
    return builder.build(
        corpus=corpus,
        recipe=recipe,
        stage=stage,
        output_dir=output_dir,
        created_utc=created_utc,
        notes=notes,
    )


def load_manifest(path: PathLike) -> PublicLegalVectorManifest:
    """Load and validate a staged public legal vector manifest."""
    target = Path(path)
    if not target.is_file():
        raise PublicLegalVectorError(f"manifest not found: {target}")
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise PublicLegalVectorError(f"invalid manifest JSON: {exc}") from exc
    if not isinstance(payload, Mapping):
        raise PublicLegalVectorError("manifest must be a JSON object")
    return PublicLegalVectorManifest.from_dict(payload)


def validate_build(result: PublicLegalVectorBuildResult) -> dict[str, Any]:
    """Return a structured validation receipt for a vector build result."""
    if result.manifest.partition != "public":
        raise PrivateTextRejectedError("build partition is not public")
    if not result.manifest.model_pin:
        raise ModelPinError("build missing model pin")
    if not result.manifest.corpus_root_cid:
        raise CorpusRootError("build missing corpus root")
    assert_known_model_pin(result.manifest.model_pin)

    recomputed = content_digest_of(result.manifest._content_body())
    if recomputed != result.manifest.index_digest_sha256:
        raise VectorIntegrityError("index digest does not match content body")
    if result.manifest.document_count != len(result.rows):
        raise VectorIntegrityError("row count does not match manifest document_count")
    for row in result.rows:
        if row.model_pin != result.manifest.model_pin:
            raise ModelPinError(
                f"row {row.record_id!r} model pin mismatch vs manifest"
            )
        if row.vector:
            if vector_content_digest([row.vector]) != row.vector_digest:
                raise VectorIntegrityError(
                    f"row {row.record_id!r} vector digest mismatch"
                )
    result.snapshot.verify_source_joins()
    return {
        "corpus_root_cid": result.manifest.corpus_root_cid,
        "dimension": result.manifest.dimension,
        "document_count": result.manifest.document_count,
        "index_digest_sha256": result.manifest.index_digest_sha256,
        "index_root_cid": result.manifest.index_root_cid,
        "model_pin": result.manifest.model_pin,
        "ok": True,
        "partition": "public",
        "stable": True,
        "task_id": TASK_ID,
    }


def validate_build_stable(
    result: PublicLegalVectorBuildResult,
    *,
    recipe: Mapping[str, Any] | None = None,
    created_utc: str = DEFAULT_CREATED_UTC,
) -> dict[str, Any]:
    """Validate and prove rebuild stability under fixed model/corpus pins."""
    base = validate_build(result)
    builder = PublicLegalVectorBuilder(require_all_families=bool(recipe is None or True))
    if recipe is not None:
        second = builder.build(recipe=recipe, created_utc=created_utc)
    else:
        second = builder.build_from_default_fixture(created_utc=created_utc)
    if second.index_root_cid != result.index_root_cid:
        raise VectorIntegrityError(
            "rebuild index_root_cid diverged under fixed model/corpus pins"
        )
    if second.index_digest_sha256 != result.index_digest_sha256:
        raise VectorIntegrityError(
            "rebuild index_digest diverged under fixed model/corpus pins"
        )
    if second.model_pin != result.model_pin:
        raise ModelPinError("rebuild model pin diverged")
    if second.corpus_root_cid != result.corpus_root_cid:
        raise CorpusRootError("rebuild corpus root diverged")
    if result.vectors and second.vectors:
        if not vectors_within_tolerance(
            result.vectors,
            second.vectors,
            tolerance=VECTOR_STABILITY_TOLERANCE,
        ):
            raise VectorIntegrityError(
                "rebuild vectors diverged under fixed model/corpus pins"
            )
    base["rebuild_index_root_cid"] = second.index_root_cid
    base["rebuild_stable"] = True
    return base


def builds_are_byte_identical(
    left: PublicLegalVectorBuildResult,
    right: PublicLegalVectorBuildResult,
) -> bool:
    """Return True when two builds share identical content-stable bytes."""
    return left.to_canonical_bytes() == right.to_canonical_bytes()


__all__ = [
    "CODE_VERSION",
    "CONFIG_ID",
    "DEFAULT_CREATED_UTC",
    "DEFAULT_MODEL_PIN",
    "DEFAULT_TENANT_ID",
    "EMBEDDING_RECEIPT_FILENAME",
    "GOAL_ID",
    "INTERFACE",
    "MANIFEST_FILENAME",
    "PRODUCER",
    "SCHEMA_VERSION",
    "SNAPSHOT_FILENAME",
    "TASK_ID",
    "VECTORS_FILENAME",
    "VECTOR_ROOT_FILENAME",
    "BuildMode",
    "CorpusRootError",
    "ModelPinError",
    "PrivateTextRejectedError",
    "PublicLegalVectorBuildResult",
    "PublicLegalVectorBuilder",
    "PublicLegalVectorError",
    "PublicLegalVectorManifest",
    "PublicLegalVectorRow",
    "SchemaValidationError",
    "VectorIntegrityError",
    "assemble_vector_snapshot",
    "assert_public_only_for_vector",
    "build_public_legal_vector_index",
    "builder_code_digest",
    "builds_are_byte_identical",
    "default_model_identity",
    "load_manifest",
    "model_identity_from_runtime",
    "validate_build",
    "validate_build_stable",
]
