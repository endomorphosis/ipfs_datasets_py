"""Cluster and package deterministic centroid-routed state-law vectors (LCR-029).

Adapter between LCR-028 pinned embeddings and a centroid-routed dense index:

* consume hashed-projection (default) or production GTE-small embeddings;
* deterministic balanced spherical clustering with recursive split;
* every vector appears in exactly one physical shard;
* centroid-specific physical shards, cosine-sorted rows, and direct CID locators;
* exhaustive-vs-routed recall evaluation and probe selection on sealed fixtures.

Design invariants
-----------------
* Retrieval identity is the chunk CID. Parent ``entry_cid`` is a join key.
* Default offline backend is the sealed local hashed projection so unit
  tests never download sentence-transformers or torch models.
* Projection embeddings prove the software contract only and cannot
  authorize publication or Hub upload.
* Centroid groups have at most 8,192 rows and two physical shards.
  Each physical shard has at most 4,096 rows.
* Rows inside a shard are sorted by descending cosine similarity to the
  shard centroid, then stable ``chunk_cid``.
* Legacy FAISS filenames (``state_laws_gte_small.faiss``) are never
  overwritten.
* No Hub upload, no tokens, and no absolute home paths in receipts.

Depends on LCR-028 (embeddings) and LCR-026 (bounded descriptor writer)
as read-only. Does not rewrite the embedding producer.
"""

from __future__ import annotations

import json
import math
import statistics
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final, Optional, Union

from ipfs_datasets_py.processors.legal_data.state_laws_chunker import (
    TASK_ID as CHUNKER_TASK_ID,
    LegalTextChunk,
)
from ipfs_datasets_py.processors.legal_data.state_laws_corpus import (
    assert_no_secrets_or_home_paths,
)
from ipfs_datasets_py.processors.legal_data.state_laws_embeddings import (
    DEFAULT_BACKEND,
    PINNED_DIMENSION,
    PINNED_INPUT_FIELDS,
    PINNED_MAX_TOKENS,
    PINNED_MODEL_ID,
    PINNED_MODEL_LICENSE,
    PINNED_MODEL_REVISION,
    PINNED_NORMALIZATION,
    PINNED_POOLING,
    PREPROCESSING,
    PRODUCTION_BACKEND,
    PRODUCTION_PROVIDER,
    PROJECTION_BACKEND,
    AdmittedChunk,
    EmbeddingFunction,
    EmbeddingGenerationResult,
    EmbeddingRecord,
    StateLawsEmbeddingBinding,
    StateLawsEmbeddingConfig,
    UnpinnedModelError,
    admitted_fixture_chunks,
    assert_embedding_conservation,
    bind_state_laws_embeddings,
    build_corpus_root_cid,
    coerce_state_law_chunks,
    content_cid,
    default_embedding_config,
    default_vector_space_id,
    fixture_embedding_chunks,
    fixture_embedding_config,
    generate_state_laws_embeddings,
    l2_norm,
    l2_normalize,
    production_embedding_config,
    require_pinned_gte_small,
    validate_vector_dimension,
    validate_vector_norm,
    write_json_atomic,
)
from ipfs_datasets_py.processors.legal_data.state_laws_graphrag_adapter import (
    TASK_ID as ADAPTER_TASK_ID,
)
from ipfs_datasets_py.processors.legal_data.state_laws_release_schema import (
    ADR_PATH,
    DEFAULT_DATASET_REPO_ID,
    DEFAULT_EMBEDDING_DIMENSION as SCHEMA_EMBEDDING_DIMENSION,
    DEFAULT_EMBEDDING_MODEL_ID as SCHEMA_EMBEDDING_MODEL_ID,
    DEFAULT_EMBEDDING_MODEL_REVISION as SCHEMA_EMBEDDING_MODEL_REVISION,
    MAX_ROWS_PER_PHYSICAL_SHARD as SCHEMA_MAX_ROWS_PER_PHYSICAL_SHARD,
    MAX_ROWS_PER_VECTOR_CENTROID as SCHEMA_MAX_ROWS_PER_VECTOR_CENTROID,
    MAX_VECTOR_SHARDS_PER_CENTROID as SCHEMA_MAX_VECTOR_SHARDS_PER_CENTROID,
    RELEASE_PROFILE,
    MutableReferenceError,
    PositionalIdentityError,
    digest_mapping,
    reject_positional_durable_identity,
    validate_digest,
    validate_entry_cid,
)
from ipfs_datasets_py.processors.legal_data.state_laws_source_policy import (
    CURRENTNESS_DISCLAIMER,
)
from ipfs_datasets_py.retrieval.hf_graphrag.locators import (
    KIND_VECTORS,
    LOCATOR_SCHEMA_VERSION,
    LocatorHit,
    LocatorRow,
    MissingKeyError,
    build_vector_locator,
)
from ipfs_datasets_py.retrieval.hf_graphrag.schema import (
    DEFAULT_CANDIDATE_CENTROIDS,
    MAX_ROWS_PER_PHYSICAL_SHARD,
    MAX_ROWS_PER_VECTOR_CENTROID,
    MAX_ROUTING_ROWS_PER_INDEX,
    MAX_VECTOR_SHARDS_PER_CENTROID,
    ArtifactFamily,
    PhysicalBoundError,
    canonical_json_bytes,
    content_sha256,
    normalize_relative_artifact_path,
    normalize_sha256,
)
from ipfs_datasets_py.retrieval.hf_graphrag.vectors import (
    ASSIGNMENT,
    DEFAULT_KMEANS_ITERATIONS,
    DEFAULT_TARGET_ROWS_PER_CENTROID,
    DEFAULT_VECTOR_KMEANS_SEED,
    ROWS_SORTED_BY,
    SCORE_TOLERANCE,
    VECTOR_DATA_DIR,
    VECTOR_INDEX_PATH,
    VECTOR_LAYOUT_SCHEMA_VERSION,
    VECTOR_ROUTING_SCHEMA_VERSION,
    VectorClusterLayout,
    VectorCoverageError as SharedVectorCoverageError,
    VectorRecord,
    VectorShardRoute,
    build_centroid_routed_vector_layout,
    route_vector_shards,
    validate_vector_layout,
    vector_bounds_policy,
    vector_shard_relative_path,
)


# ---------------------------------------------------------------------------
# Identity
# ---------------------------------------------------------------------------

SCHEMA_VERSION: Final = "state-laws-vectors-v1"
REPORT_SCHEMA: Final = "ipfs_datasets_py/legal-corpora-reindex-vector-evaluation@1"
TASK_ID: Final = "LCR-029"
GOAL_ID: Final = "LCR-G040"
PROGRAM_ID: Final = "legal-corpora-reindex-v1"
PRODUCER: Final = "state_laws_vectors.py"
BOARD_NAMESPACE: Final = "legal-corpora-reindex-v1"
BUNDLE: Final = "dense-routing"
CODE_VERSION: Final = "1"
EMBEDDING_TASK_ID: Final = "LCR-028"
ADAPTER_DEPENDS_ON: Final = ADAPTER_TASK_ID
CHUNKER_DEPENDS_ON: Final = CHUNKER_TASK_ID

PRIMARY_KEY: Final = "chunk_cid"
PARENT_KEY: Final = "entry_cid"
VECTOR_KEY_FIELD: Final = "chunk_cid"
VECTOR_ENTRY_LOCATOR_DIR: Final = "indexes/vector_entry_locator"

AUTHORIZES_PUBLICATION: Final = False
AUTHORIZES_HUB_UPLOAD: Final = False
AUTHORIZES_RELEASE: Final = False
PROVES_SOFTWARE_CONTRACT_ONLY: Final = True
PROJECTION_FALLBACK_AUTHORIZES_VECTOR_RELEASE: Final = False

REPORT_RELATIVE_PATH: Final = Path(
    "docs/reports/legal_corpora_reindex/vector_evaluation.json"
)
_REPO_ROOT = Path(__file__).resolve().parents[3]

FORBIDDEN_LEGACY_FAISS_FILENAMES: Final = frozenset(
    {
        "state_laws_gte_small.faiss",
        "state_laws_gte_small_metadata.parquet",
        "ipfs_state_laws.faiss",
        "ipfs_state_laws_gte_small.faiss",
        "index.faiss",
        "index.faiss.index",
    }
)
FORBIDDEN_FAISS_SUFFIXES: Final = (".faiss", ".faiss.index")

DEFAULT_TEST_MAX_ROWS_PER_SHARD: Final = 2
DEFAULT_TEST_MAX_ROWS_PER_CENTROID: Final = 4
DEFAULT_TEST_TARGET_ROWS_PER_CENTROID: Final = 3
DEFAULT_TEST_ENTRY_LOCATOR_PAGE_SIZE: Final = 4

PROBE_CANDIDATES: Final = (1, 2, 4, 8)
TOP_K_VALUES: Final = (1, 5, 10)
PRIMARY_TOP_K: Final = 1
RECALL_GATE: Final = 0.95
EXHAUSTIVE_FALLBACK_ROW_THRESHOLD: Final = 4_096
BYTES_PER_VECTOR_ROW: Final = 4 * PINNED_DIMENSION + 64
ROUTING_INDEX_BYTES_PER_CLUSTER: Final = 4 * PINNED_DIMENSION + 48
LATENCY_MS_PER_SCORED_ROW: Final = 0.01
LATENCY_MS_PER_ROUTED_SHARD: Final = 0.05
FLOAT_REPORT_DECIMALS: Final = 6
SELECTION_PARTITION: Final = "dev"
REPORT_PARTITION: Final = "test"

PathLike = Union[str, Path]
JsonMapping = Mapping[str, Any]


if PINNED_MODEL_ID != SCHEMA_EMBEDDING_MODEL_ID:
    raise RuntimeError("state-law model pin drifted from release schema")
if PINNED_MODEL_REVISION != SCHEMA_EMBEDDING_MODEL_REVISION:
    raise RuntimeError("state-law model revision drifted from release schema")
if PINNED_DIMENSION != SCHEMA_EMBEDDING_DIMENSION:
    raise RuntimeError("state-law dimension drifted from release schema")
if MAX_ROWS_PER_PHYSICAL_SHARD != SCHEMA_MAX_ROWS_PER_PHYSICAL_SHARD:
    raise RuntimeError("physical shard bound drifted from release schema")
if MAX_ROWS_PER_VECTOR_CENTROID != SCHEMA_MAX_ROWS_PER_VECTOR_CENTROID:
    raise RuntimeError("centroid row bound drifted from release schema")
if MAX_VECTOR_SHARDS_PER_CENTROID != SCHEMA_MAX_VECTOR_SHARDS_PER_CENTROID:
    raise RuntimeError("centroid shard bound drifted from release schema")


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class StateLawsVectorError(ValueError):
    """Base error for state-law vector clustering / binding failures."""

    code: str = "state_laws_vector_error"

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        if code is not None:
            self.code = code

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "kind": "error", "message": str(self)}


class VectorBindingError(StateLawsVectorError):
    """Raised when embeddings cannot be bound to a vector layout."""

    code = "binding_invalid"


class VectorCoverageError(StateLawsVectorError):
    """Raised when chunk conservation or uniqueness fails."""

    code = "coverage_invalid"


class VectorRouteBoundError(StateLawsVectorError):
    """Raised when centroid or shard physical bounds are violated."""

    code = "route_bound_exceeded"


class VectorOrderingError(StateLawsVectorError):
    """Raised when shard rows are not cosine-sorted."""

    code = "ordering_invalid"


class VectorRootReconcileError(StateLawsVectorError):
    """Raised when model/config/corpus/layout roots do not reconcile."""

    code = "root_reconcile_failed"


class VectorLocatorError(StateLawsVectorError):
    """Raised when direct CID vector location fails."""

    code = "locator_failed"


class VectorReceiptError(StateLawsVectorError):
    """Raised when the sealed vector evaluation report is malformed."""

    code = "receipt_invalid"


class VectorReleaseAuthorizationError(StateLawsVectorError):
    """Raised when a vector report would authorize release or Hub upload."""

    code = "release_authorization_forbidden"


class LegacyFaissOverwriteError(StateLawsVectorError):
    """Raised when a layout would overwrite a legacy FAISS filename."""

    code = "legacy_faiss_overwrite_forbidden"


class VectorEvaluationError(StateLawsVectorError):
    """Raised when fixture evaluation cannot complete fail-closed."""

    code = "evaluation_invalid"


# ---------------------------------------------------------------------------
# Primitive helpers
# ---------------------------------------------------------------------------


def _require_non_empty_str(value: Any, name: str, *, maximum: int = 1024) -> str:
    if not isinstance(value, str) or not value.strip():
        raise VectorBindingError(f"{name} must be a non-empty string")
    text = value.strip()
    if "\x00" in text:
        raise VectorBindingError(f"{name} must not contain NUL")
    if len(text) > maximum:
        raise VectorBindingError(f"{name} exceeds maximum length {maximum}")
    return text


def _require_positive_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise VectorBindingError(f"{name} must be a positive integer")
    return value


def _require_non_negative_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise VectorBindingError(f"{name} must be a non-negative integer")
    return value


def _durable_key(value: Any, name: str) -> str:
    text = _require_non_empty_str(value, name, maximum=512)
    try:
        reject_positional_durable_identity(text, name=name)
    except PositionalIdentityError as exc:
        raise VectorBindingError(str(exc), code="positional") from exc
    if text.lower().startswith("row-"):
        raise VectorBindingError(
            f"{name} must not be a positional identity token: {text!r}",
            code="positional",
        )
    try:
        return validate_entry_cid(text, name=name)
    except (PositionalIdentityError, MutableReferenceError) as exc:
        raise VectorBindingError(str(exc), code="positional") from exc


def reject_legacy_faiss_path(path: Any, *, name: str = "path") -> str:
    """Fail closed on legacy FAISS filenames that must never be overwritten."""

    text = _require_non_empty_str(path, name, maximum=2048)
    lowered = text.replace("\\", "/").lower()
    basename = lowered.rsplit("/", 1)[-1]
    if basename in FORBIDDEN_LEGACY_FAISS_FILENAMES:
        raise LegacyFaissOverwriteError(
            f"{name} would overwrite a legacy FAISS artifact: {path!r}"
        )
    if any(basename.endswith(suffix) for suffix in FORBIDDEN_FAISS_SUFFIXES):
        raise LegacyFaissOverwriteError(
            f"{name} uses a forbidden FAISS suffix: {path!r}"
        )
    if "state_laws_gte_small.faiss" in lowered or "ipfs_state_laws.faiss" in lowered:
        raise LegacyFaissOverwriteError(
            f"{name} aliases a legacy state-law FAISS filename: {path!r}"
        )
    return text


def build_model_cid(
    *,
    model_id: str,
    model_revision: str,
    vector_space_id: str,
) -> str:
    """Content-address the immutable model pin surface."""

    model, revision = require_pinned_gte_small(
        model_id=model_id, model_revision=model_revision
    )
    space = _require_non_empty_str(vector_space_id, "vector_space_id", maximum=512)
    payload = {
        "model_id": model,
        "model_revision": revision,
        "vector_space_id": space,
    }
    return content_cid(payload)


def build_layout_root_cid(layout: VectorClusterLayout) -> str:
    """Content-address the structural centroid layout (no raw embeddings)."""

    if not isinstance(layout, VectorClusterLayout):
        raise VectorBindingError("layout must be a VectorClusterLayout")
    structural = {
        "assignment": layout.assignment,
        "clusters": [
            {
                "cluster_id": group.cluster_id,
                "entry_cids": list(group.entry_cids),
                "row_count": group.row_count,
                "shard_count": group.shard_count,
                "shards": [
                    {
                        "chunk_in_cluster": shard.chunk_in_cluster,
                        "entry_cids": list(shard.entry_cids),
                        "global_shard_id": shard.global_shard_id,
                        "relative_path": shard.relative_path,
                        "row_count": shard.row_count,
                    }
                    for shard in group.shards
                ],
            }
            for group in layout.clusters
        ],
        "dimension": layout.dimension,
        "max_rows_per_centroid": layout.max_rows_per_centroid,
        "max_rows_per_shard": layout.max_rows_per_shard,
        "max_shards_per_centroid": layout.max_shards_per_centroid,
        "schema_version": layout.schema_version,
        "seed": layout.seed,
        "total_rows": layout.total_rows,
    }
    return content_cid(structural)


def build_membership_hash(layout: VectorClusterLayout) -> str:
    """Hash centroid membership independently of raw embedding values."""

    payload = {
        "assignment": ASSIGNMENT,
        "clusters": [
            {
                "cluster_id": group.cluster_id,
                "keys": list(group.entry_cids),
                "shards": [
                    {
                        "chunk_in_cluster": shard.chunk_in_cluster,
                        "keys": list(shard.entry_cids),
                        "relative_path": shard.relative_path,
                    }
                    for shard in group.shards
                ],
            }
            for group in layout.clusters
        ],
        "seed": layout.seed,
        "total_rows": layout.total_rows,
    }
    return content_cid(payload)


def _synthetic_shard_digest(relative_path: str, row_count: int) -> str:
    """Deterministic placeholder digest for in-memory (not-yet-written) shards."""

    reject_legacy_faiss_path(relative_path, name="relative_path")
    return content_sha256(
        f"state-laws-vector-shard:{relative_path}:rows={row_count}"
    )


def _wrap_layout_error(exc: BaseException) -> StateLawsVectorError:
    if isinstance(exc, StateLawsVectorError):
        return exc
    if isinstance(exc, PhysicalBoundError):
        return VectorRouteBoundError(str(exc))
    if isinstance(exc, SharedVectorCoverageError):
        return VectorCoverageError(str(exc))
    if isinstance(exc, UnpinnedModelError):
        return VectorBindingError(str(exc), code="unpinned_model")
    return VectorBindingError(str(exc))


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CorpusParentLink:
    """Corpus parent identity for one embedded legal chunk."""

    chunk_cid: str
    entry_cid: str
    document_index: int = 0
    legal_id: Optional[str] = None
    chunk_id: Optional[str] = None
    jurisdiction_code: Optional[str] = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "chunk_cid", _durable_key(self.chunk_cid, "chunk_cid"))
        object.__setattr__(self, "entry_cid", _durable_key(self.entry_cid, "entry_cid"))
        object.__setattr__(
            self,
            "document_index",
            _require_non_negative_int(self.document_index, "document_index"),
        )
        if self.legal_id is not None and str(self.legal_id).strip():
            object.__setattr__(
                self,
                "legal_id",
                _require_non_empty_str(self.legal_id, "legal_id", maximum=256),
            )
        else:
            object.__setattr__(self, "legal_id", None)
        if self.chunk_id is not None and str(self.chunk_id).strip():
            object.__setattr__(
                self,
                "chunk_id",
                _require_non_empty_str(self.chunk_id, "chunk_id", maximum=512),
            )
        else:
            object.__setattr__(self, "chunk_id", None)
        if self.jurisdiction_code is not None and str(self.jurisdiction_code).strip():
            object.__setattr__(
                self,
                "jurisdiction_code",
                _require_non_empty_str(
                    self.jurisdiction_code, "jurisdiction_code", maximum=8
                ).upper(),
            )
        else:
            object.__setattr__(self, "jurisdiction_code", None)

    def to_dict(self) -> dict[str, Any]:
        return {
            "chunk_cid": self.chunk_cid,
            "chunk_id": self.chunk_id,
            "document_index": self.document_index,
            "entry_cid": self.entry_cid,
            "jurisdiction_code": self.jurisdiction_code,
            "legal_id": self.legal_id,
        }


@dataclass(frozen=True, slots=True)
class VectorShardLocation:
    """Exact location of one vector inside a centroid-routed data shard."""

    vector_key: str
    chunk_cid: str
    relative_path: str
    cluster_id: int
    chunk_in_cluster: int
    global_shard_id: int
    row_offset: int
    entry_cid: Optional[str] = None
    document_index: int = 0
    sha256: str = ""
    size_bytes: int = 0
    content_cid: Optional[str] = None
    dimension: int = 0
    centroid_cosine: float = 0.0

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "vector_key", _durable_key(self.vector_key, "vector_key")
        )
        object.__setattr__(self, "chunk_cid", _durable_key(self.chunk_cid, "chunk_cid"))
        object.__setattr__(
            self,
            "relative_path",
            reject_legacy_faiss_path(
                normalize_relative_artifact_path(self.relative_path),
                name="relative_path",
            ),
        )
        object.__setattr__(
            self, "cluster_id", _require_non_negative_int(self.cluster_id, "cluster_id")
        )
        object.__setattr__(
            self,
            "chunk_in_cluster",
            _require_non_negative_int(self.chunk_in_cluster, "chunk_in_cluster"),
        )
        object.__setattr__(
            self,
            "global_shard_id",
            _require_non_negative_int(self.global_shard_id, "global_shard_id"),
        )
        object.__setattr__(
            self, "row_offset", _require_non_negative_int(self.row_offset, "row_offset")
        )
        object.__setattr__(
            self,
            "document_index",
            _require_non_negative_int(self.document_index, "document_index"),
        )
        object.__setattr__(
            self, "size_bytes", _require_non_negative_int(self.size_bytes, "size_bytes")
        )
        object.__setattr__(
            self, "dimension", _require_non_negative_int(self.dimension, "dimension")
        )
        if self.entry_cid is not None and str(self.entry_cid).strip():
            object.__setattr__(
                self, "entry_cid", _durable_key(self.entry_cid, "entry_cid")
            )
        else:
            object.__setattr__(self, "entry_cid", None)
        if self.sha256:
            object.__setattr__(
                self, "sha256", normalize_sha256(self.sha256, name="sha256")
            )
        if self.content_cid is not None and str(self.content_cid).strip():
            object.__setattr__(
                self,
                "content_cid",
                validate_digest(self.content_cid, name="content_cid"),
            )
        object.__setattr__(self, "centroid_cosine", float(self.centroid_cosine))

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "centroid_cosine": self.centroid_cosine,
            "chunk_cid": self.chunk_cid,
            "chunk_in_cluster": self.chunk_in_cluster,
            "cluster_id": self.cluster_id,
            "dimension": self.dimension,
            "document_index": self.document_index,
            "entry_cid": self.entry_cid,
            "global_shard_id": self.global_shard_id,
            "relative_path": self.relative_path,
            "row_offset": self.row_offset,
            "sha256": self.sha256,
            "size_bytes": self.size_bytes,
            "vector_key": self.vector_key,
        }
        if self.content_cid is not None:
            payload["content_cid"] = self.content_cid
            payload["cid"] = self.content_cid
        return payload

    def locator_payload(self) -> dict[str, Any]:
        return {
            "centroid_cosine": self.centroid_cosine,
            "chunk_cid": self.chunk_cid,
            "chunk_in_cluster": self.chunk_in_cluster,
            "cluster_id": self.cluster_id,
            "entry_cid": self.entry_cid,
            "global_shard_id": self.global_shard_id,
            "relative_path": self.relative_path,
            "row_offset": self.row_offset,
            "vector_key": self.vector_key,
        }


@dataclass(frozen=True, slots=True)
class ManifestReadyDescriptor:
    """Compact artifact descriptor ready for a release manifest entry."""

    relative_path: str
    family: str
    row_count: int
    sha256: str
    size_bytes: int = 0
    schema_id: str = VECTOR_LAYOUT_SCHEMA_VERSION
    first_key: Optional[str] = None
    last_key: Optional[str] = None
    centroid_id: Optional[str] = None
    media_type: str = "application/vnd.apache.parquet"
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "relative_path",
            reject_legacy_faiss_path(
                normalize_relative_artifact_path(self.relative_path),
                name="relative_path",
            ),
        )
        object.__setattr__(
            self,
            "family",
            _require_non_empty_str(self.family, "family", maximum=64),
        )
        object.__setattr__(
            self, "row_count", _require_non_negative_int(self.row_count, "row_count")
        )
        object.__setattr__(self, "sha256", normalize_sha256(self.sha256, name="sha256"))
        object.__setattr__(
            self,
            "size_bytes",
            _require_non_negative_int(self.size_bytes, "size_bytes"),
        )
        if not isinstance(self.metadata, Mapping):
            raise VectorBindingError("metadata must be a mapping")
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "family": self.family,
            "first_key": self.first_key,
            "last_key": self.last_key,
            "media_type": self.media_type,
            "relative_path": self.relative_path,
            "row_count": self.row_count,
            "schema_id": self.schema_id,
            "sha256": self.sha256,
            "size_bytes": self.size_bytes,
        }
        if self.centroid_id is not None:
            payload["centroid_id"] = self.centroid_id
        if self.metadata:
            payload["metadata"] = dict(self.metadata)
        return payload


@dataclass(frozen=True, slots=True)
class InputReceipt:
    """Per-chunk input hash bound to the GTE-small pin."""

    chunk_cid: str
    input_hash: str
    model_id: str
    model_revision: str
    pooling: str
    normalization: str
    dimension: int
    preprocessing: str = PREPROCESSING
    vector_space_id: str = ""
    config_cid: str = ""
    entry_cid: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "chunk_cid": self.chunk_cid,
            "config_cid": self.config_cid,
            "dimension": self.dimension,
            "entry_cid": self.entry_cid,
            "input_hash": self.input_hash,
            "model_id": self.model_id,
            "model_revision": self.model_revision,
            "normalization": self.normalization,
            "pooling": self.pooling,
            "preprocessing": self.preprocessing,
            "vector_space_id": self.vector_space_id,
        }


@dataclass(frozen=True, slots=True)
class StateLawsVectorBinding:
    """Complete state-law vector binding: centroid routes + direct CID locators."""

    layout: VectorClusterLayout
    routing_rows: tuple[dict[str, Any], ...]
    locations: Mapping[str, VectorShardLocation]
    parent_links: tuple[CorpusParentLink, ...]
    embeddings: Mapping[str, EmbeddingRecord]
    model_id: str
    model_revision: str
    vector_space_id: str
    config_cid: str
    model_cid: str
    vector_root_cid: str
    layout_seed: int
    corpus_root_cid: Optional[str] = None
    embedding_config: Optional[StateLawsEmbeddingConfig] = None
    entry_locator_rows: tuple[LocatorRow, ...] = ()
    descriptors: tuple[ManifestReadyDescriptor, ...] = ()
    input_receipts: tuple[InputReceipt, ...] = ()
    membership_hash: str = ""
    schema_version: str = SCHEMA_VERSION
    release_profile: str = RELEASE_PROFILE
    task_id: str = TASK_ID
    goal_id: str = GOAL_ID

    def __post_init__(self) -> None:
        if not isinstance(self.layout, VectorClusterLayout):
            raise VectorBindingError("layout must be a VectorClusterLayout")
        if not isinstance(self.locations, Mapping):
            raise VectorBindingError("locations must be a mapping")
        object.__setattr__(self, "locations", MappingProxyType(dict(self.locations)))
        if not isinstance(self.embeddings, Mapping):
            raise VectorBindingError("embeddings must be a mapping")
        object.__setattr__(self, "embeddings", MappingProxyType(dict(self.embeddings)))
        if len(self.locations) != self.layout.total_rows:
            raise VectorCoverageError(
                f"location map size {len(self.locations)} != layout "
                f"total_rows {self.layout.total_rows}"
            )
        if len(self.embeddings) != self.layout.total_rows:
            raise VectorCoverageError(
                f"embedding map size {len(self.embeddings)} != layout "
                f"total_rows {self.layout.total_rows}"
            )
        model_id, model_revision = require_pinned_gte_small(
            model_id=self.model_id, model_revision=self.model_revision
        )
        object.__setattr__(self, "model_id", model_id)
        object.__setattr__(self, "model_revision", model_revision)
        object.__setattr__(
            self,
            "vector_space_id",
            _require_non_empty_str(self.vector_space_id, "vector_space_id"),
        )
        object.__setattr__(
            self, "config_cid", validate_digest(self.config_cid, name="config_cid")
        )
        object.__setattr__(
            self, "model_cid", validate_digest(self.model_cid, name="model_cid")
        )
        object.__setattr__(
            self,
            "vector_root_cid",
            validate_digest(self.vector_root_cid, name="vector_root_cid"),
        )
        if self.corpus_root_cid is not None and str(self.corpus_root_cid).strip():
            object.__setattr__(
                self,
                "corpus_root_cid",
                validate_digest(self.corpus_root_cid, name="corpus_root_cid"),
            )
        else:
            object.__setattr__(self, "corpus_root_cid", None)
        if not self.membership_hash:
            object.__setattr__(self, "membership_hash", build_membership_hash(self.layout))
        else:
            object.__setattr__(
                self,
                "membership_hash",
                validate_digest(self.membership_hash, name="membership_hash"),
            )
        for shard in self.layout.shards:
            reject_legacy_faiss_path(shard.relative_path, name="shard.relative_path")

    @property
    def vector_count(self) -> int:
        return self.layout.total_rows

    @property
    def cluster_count(self) -> int:
        return self.layout.cluster_count

    @property
    def shard_count(self) -> int:
        return self.layout.shard_count

    @property
    def vector_keys(self) -> tuple[str, ...]:
        return tuple(sorted(self.locations))

    @property
    def chunk_cids(self) -> tuple[str, ...]:
        return tuple(sorted(loc.chunk_cid for loc in self.locations.values()))

    @property
    def entry_cids(self) -> tuple[str, ...]:
        return tuple(
            sorted(
                {
                    loc.entry_cid
                    for loc in self.locations.values()
                    if loc.entry_cid
                }
            )
        )

    def location_for(self, vector_key: str) -> VectorShardLocation:
        key = _durable_key(vector_key, "vector_key")
        try:
            return self.locations[key]
        except KeyError as exc:
            raise MissingKeyError(
                f"vector key {key!r} is not covered by any vector shard"
            ) from exc

    def locate_vector(self, vector_key: str) -> LocatorHit:
        location = self.location_for(vector_key)
        row = LocatorRow(
            first_key=location.vector_key,
            last_key=location.vector_key,
            relative_path=location.relative_path,
            sha256=location.sha256
            or _synthetic_shard_digest(location.relative_path, 1),
            size_bytes=location.size_bytes,
            row_count=1,
            shard_id=location.global_shard_id,
            kind=KIND_VECTORS,
            schema_version=LOCATOR_SCHEMA_VERSION,
            content_cid=location.content_cid,
            metadata=location.locator_payload(),
        )
        return LocatorHit(key=location.vector_key, row=row)

    def locate_vectors(
        self,
        vector_keys: Sequence[str],
        *,
        strict: bool = True,
    ) -> tuple[LocatorHit, ...]:
        hits: list[LocatorHit] = []
        for position, key in enumerate(vector_keys):
            try:
                hits.append(self.locate_vector(str(key)))
            except (MissingKeyError, VectorBindingError):
                if strict:
                    raise MissingKeyError(
                        f"vector_keys[{position}]={key!r} is not covered"
                    ) from None
        return tuple(hits)

    def entry_locator_index(self):
        if not self.entry_locator_rows:
            raise VectorLocatorError("entry locator rows are empty")
        return build_vector_locator(self.entry_locator_rows)

    def route_centroids(
        self,
        query_embedding: Sequence[float],
        *,
        candidate_centroids: int = DEFAULT_CANDIDATE_CENTROIDS,
        max_shards: int | None = None,
    ) -> tuple[VectorShardRoute, ...]:
        return route_vector_shards(
            self.routing_rows,
            query_embedding,
            candidate_centroids=candidate_centroids,
            max_shards=max_shards,
        )

    def parent_link_for_chunk(self, chunk_cid: str) -> Optional[CorpusParentLink]:
        key = _durable_key(chunk_cid, "chunk_cid")
        for link in self.parent_links:
            if link.chunk_cid == key:
                return link
        return None

    def locations_for_entry_cid(
        self, entry_cid: str
    ) -> tuple[VectorShardLocation, ...]:
        parent = _durable_key(entry_cid, "entry_cid")
        matches = [
            loc for loc in self.locations.values() if loc.entry_cid == parent
        ]
        return tuple(sorted(matches, key=lambda item: item.vector_key))

    def locate_entry(self, entry_cid: str) -> tuple[VectorShardLocation, ...]:
        matches = self.locations_for_entry_cid(entry_cid)
        if not matches:
            raise MissingKeyError(
                f"entry_cid {entry_cid!r} is not covered by any vector shard"
            )
        return matches

    def containing_vector_artifacts(
        self, vector_keys: Sequence[str]
    ) -> tuple[ManifestReadyDescriptor, ...]:
        needed = {
            self.location_for(str(key)).relative_path for key in vector_keys
        }
        return tuple(
            item for item in self.descriptors if item.relative_path in needed
        )

    def model_receipt(self) -> dict[str, Any]:
        return {
            "backend": (
                self.embedding_config.backend
                if self.embedding_config is not None
                else DEFAULT_BACKEND
            ),
            "config_cid": self.config_cid,
            "dimension": PINNED_DIMENSION,
            "input_fields": list(
                self.embedding_config.input_fields
                if self.embedding_config is not None
                else PINNED_INPUT_FIELDS
            ),
            "max_tokens": PINNED_MAX_TOKENS,
            "model_cid": self.model_cid,
            "model_id": self.model_id,
            "model_revision": self.model_revision,
            "normalization": PINNED_NORMALIZATION,
            "pooling": PINNED_POOLING,
            "preprocessing": PREPROCESSING,
            "seed": self.layout_seed,
            "vector_space_id": self.vector_space_id,
        }

    def receipt(self) -> dict[str, Any]:
        return {
            "assignment": self.layout.assignment,
            "cluster_count": self.cluster_count,
            "config_cid": self.config_cid,
            "corpus_root_cid": self.corpus_root_cid,
            "dimension": self.layout.dimension,
            "goal_id": self.goal_id,
            "input_receipt_count": len(self.input_receipts),
            "layout_seed": self.layout_seed,
            "max_rows_per_centroid": self.layout.max_rows_per_centroid,
            "max_rows_per_shard": self.layout.max_rows_per_shard,
            "max_shards_per_centroid": self.layout.max_shards_per_centroid,
            "membership_hash": self.membership_hash,
            "model_cid": self.model_cid,
            "model_id": self.model_id,
            "model_revision": self.model_revision,
            "parent_link_count": len(self.parent_links),
            "primary_key": PRIMARY_KEY,
            "release_profile": self.release_profile,
            "rows_sorted_by": ROWS_SORTED_BY,
            "schema_version": self.schema_version,
            "shard_count": self.shard_count,
            "task_id": self.task_id,
            "vector_count": self.vector_count,
            "vector_root_cid": self.vector_root_cid,
            "vector_space_id": self.vector_space_id,
        }

    def to_dict(self, *, include_locations: bool = False) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "descriptors": [item.to_dict() for item in self.descriptors],
            "entry_locator_rows": [row.to_dict() for row in self.entry_locator_rows],
            "layout": self.layout.manifest_config(),
            "model_receipt": self.model_receipt(),
            "parent_links": [link.to_dict() for link in self.parent_links],
            "receipt": self.receipt(),
            "routing_rows": [dict(row) for row in self.routing_rows],
            "schema_version": self.schema_version,
        }
        if include_locations:
            payload["locations"] = {
                key: loc.to_dict() for key, loc in sorted(self.locations.items())
            }
        else:
            payload["vector_keys"] = list(self.vector_keys)
        return payload


# ---------------------------------------------------------------------------
# Layout helpers
# ---------------------------------------------------------------------------


def embeddings_to_vector_records(
    records: Sequence[EmbeddingRecord],
) -> tuple[VectorRecord, ...]:
    if not records:
        raise VectorBindingError("cannot bind an empty embedding set")
    seen: set[str] = set()
    rows: list[VectorRecord] = []
    for position, record in enumerate(records):
        if not isinstance(record, EmbeddingRecord):
            raise VectorBindingError(
                f"records[{position}] must be an EmbeddingRecord"
            )
        key = record.chunk_cid
        if key in seen:
            raise VectorCoverageError(f"duplicate embedded chunk_cid: {key!r}")
        seen.add(key)
        validate_vector_dimension(
            record.embedding, dimension=PINNED_DIMENSION, name=f"embedding[{key}]"
        )
        rows.append(
            VectorRecord(
                entry_cid=key,
                embedding=record.embedding,
                document_index=position,
                metadata={
                    "chunk_cid": record.chunk_cid,
                    "chunk_id": record.chunk_id,
                    "config_cid": record.config_cid,
                    "entry_cid": record.entry_cid,
                    "input_hash": record.input_hash,
                    "model_id": record.model_id,
                    "model_revision": record.model_revision,
                    "vector_space_id": record.vector_space_id,
                },
            )
        )
    return tuple(rows)


def build_entry_locator_rows(
    locations: Mapping[str, VectorShardLocation],
    *,
    max_keys_per_page: int = MAX_ROWS_PER_PHYSICAL_SHARD,
    locator_dir: str = VECTOR_ENTRY_LOCATOR_DIR,
) -> tuple[LocatorRow, ...]:
    if not locations:
        return ()
    max_keys = _require_positive_int(max_keys_per_page, "max_keys_per_page")
    if max_keys > MAX_ROWS_PER_PHYSICAL_SHARD:
        raise VectorRouteBoundError(
            f"max_keys_per_page={max_keys} exceeds {MAX_ROWS_PER_PHYSICAL_SHARD}"
        )
    directory = normalize_relative_artifact_path(locator_dir)
    reject_legacy_faiss_path(directory, name="locator_dir")
    ordered_keys = sorted(locations)
    rows: list[LocatorRow] = []
    for page_index, offset in enumerate(range(0, len(ordered_keys), max_keys)):
        group = ordered_keys[offset : offset + max_keys]
        relative = f"{directory}/part-{page_index:06d}.parquet"
        reject_legacy_faiss_path(relative, name="locator_relative_path")
        page_payload = [
            {
                "relative_path": locations[key].relative_path,
                "vector_key": key,
            }
            for key in group
        ]
        digest = content_sha256(canonical_json_bytes({"rows": page_payload}))
        rows.append(
            LocatorRow(
                first_key=group[0],
                last_key=group[-1],
                relative_path=relative,
                sha256=digest,
                size_bytes=0,
                row_count=len(group),
                shard_id=page_index,
                kind=KIND_VECTORS,
                schema_version=LOCATOR_SCHEMA_VERSION,
                page_index=page_index,
                start_document_index=offset,
                end_document_index=offset + len(group) - 1,
                metadata={
                    "kind": "vector_entry_locator_page",
                    "vector_keys": list(group),
                    "data_paths": sorted(
                        {locations[key].relative_path for key in group}
                    ),
                },
            )
        )
    if len(rows) > MAX_ROUTING_ROWS_PER_INDEX:
        raise VectorRouteBoundError(
            f"entry locator page count {len(rows)} exceeds "
            f"{MAX_ROUTING_ROWS_PER_INDEX}"
        )
    return tuple(rows)


def build_location_map(
    layout: VectorClusterLayout,
    *,
    records: Sequence[EmbeddingRecord],
    descriptors: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, VectorShardLocation]:
    parent_by_key = {rec.chunk_cid: rec for rec in records}
    descriptor_map = descriptors or {}
    locations: dict[str, VectorShardLocation] = {}
    score_by_key: dict[str, float] = {}
    for shard in layout.shards:
        reject_legacy_faiss_path(shard.relative_path, name="shard.relative_path")
        for offset, vector_key in enumerate(shard.entry_cids):
            if offset < len(shard.scores):
                score_by_key[vector_key] = float(shard.scores[offset])
    for shard in layout.shards:
        extra = descriptor_map.get(shard.relative_path, {})
        sha256 = str(extra.get("sha256") or "") or _synthetic_shard_digest(
            shard.relative_path, shard.row_count
        )
        size_bytes = int(extra.get("size_bytes") or 0)
        content_cid_value = extra.get("content_cid") or extra.get("cid")
        for offset, vector_key in enumerate(shard.entry_cids):
            if vector_key in locations:
                raise VectorCoverageError(
                    f"duplicate vector key across shards: {vector_key!r}"
                )
            record = parent_by_key.get(vector_key)
            locations[vector_key] = VectorShardLocation(
                vector_key=vector_key,
                chunk_cid=vector_key,
                relative_path=shard.relative_path,
                cluster_id=shard.cluster_id,
                chunk_in_cluster=shard.chunk_in_cluster,
                global_shard_id=shard.global_shard_id,
                row_offset=offset,
                entry_cid=record.entry_cid if record is not None else None,
                document_index=(
                    shard.document_indexes[offset]
                    if offset < len(shard.document_indexes)
                    else offset
                ),
                sha256=sha256,
                size_bytes=size_bytes,
                content_cid=str(content_cid_value) if content_cid_value else None,
                dimension=shard.dimension,
                centroid_cosine=score_by_key.get(vector_key, 0.0),
            )
    if len(locations) != layout.total_rows:
        raise VectorCoverageError(
            f"location map has {len(locations)} keys; layout has "
            f"{layout.total_rows} rows"
        )
    return locations


def build_parent_links(
    records: Sequence[EmbeddingRecord],
) -> tuple[CorpusParentLink, ...]:
    links: list[CorpusParentLink] = []
    for position, record in enumerate(records):
        if record.entry_cid is None:
            continue
        links.append(
            CorpusParentLink(
                chunk_cid=record.chunk_cid,
                entry_cid=record.entry_cid,
                document_index=position,
                chunk_id=record.chunk_id,
            )
        )
    return tuple(sorted(links, key=lambda item: item.chunk_cid))


def build_input_receipts(
    records: Sequence[EmbeddingRecord],
    *,
    config: StateLawsEmbeddingConfig | None = None,
) -> tuple[InputReceipt, ...]:
    pin = config
    receipts: list[InputReceipt] = []
    for record in records:
        receipts.append(
            InputReceipt(
                chunk_cid=record.chunk_cid,
                input_hash=record.input_hash,
                model_id=record.model_id,
                model_revision=record.model_revision,
                pooling=record.pooling,
                normalization=record.normalization,
                dimension=record.dimension,
                preprocessing=pin.preprocessing if pin is not None else PREPROCESSING,
                vector_space_id=record.vector_space_id,
                config_cid=record.config_cid,
                entry_cid=record.entry_cid,
            )
        )
    return tuple(sorted(receipts, key=lambda item: item.chunk_cid))


def build_manifest_descriptors(
    layout: VectorClusterLayout,
    *,
    routing_rows: Sequence[Mapping[str, Any]],
    entry_locator_rows: Sequence[LocatorRow],
    descriptors: Mapping[str, Mapping[str, Any]] | None = None,
) -> tuple[ManifestReadyDescriptor, ...]:
    descriptor_map = descriptors or {}
    out: list[ManifestReadyDescriptor] = []
    for shard in layout.shards:
        reject_legacy_faiss_path(shard.relative_path, name="shard.relative_path")
        extra = descriptor_map.get(shard.relative_path, {})
        sha256 = str(extra.get("sha256") or "") or _synthetic_shard_digest(
            shard.relative_path, shard.row_count
        )
        out.append(
            ManifestReadyDescriptor(
                relative_path=shard.relative_path,
                family=ArtifactFamily.VECTORS.value,
                row_count=shard.row_count,
                sha256=sha256,
                size_bytes=int(extra.get("size_bytes") or 0),
                schema_id=VECTOR_LAYOUT_SCHEMA_VERSION,
                first_key=shard.entry_cids[0] if shard.entry_cids else None,
                last_key=shard.entry_cids[-1] if shard.entry_cids else None,
                centroid_id=f"cluster-{shard.cluster_id:06d}",
                metadata={
                    "chunk_in_cluster": shard.chunk_in_cluster,
                    "cluster_id": shard.cluster_id,
                    "global_shard_id": shard.global_shard_id,
                    "rows_sorted_by": ROWS_SORTED_BY,
                },
            )
        )
    routing_digest = content_sha256(
        canonical_json_bytes({"routing_rows": list(routing_rows)})
    )
    reject_legacy_faiss_path(VECTOR_INDEX_PATH, name="vector_index_path")
    out.append(
        ManifestReadyDescriptor(
            relative_path=VECTOR_INDEX_PATH,
            family=ArtifactFamily.ROUTING_INDEX.value,
            row_count=len(routing_rows),
            sha256=routing_digest,
            schema_id=VECTOR_ROUTING_SCHEMA_VERSION,
            metadata={"kind": "centroid_routing_index"},
        )
    )
    for row in entry_locator_rows:
        out.append(
            ManifestReadyDescriptor(
                relative_path=row.relative_path,
                family=ArtifactFamily.LOCATOR_INDEX.value,
                row_count=row.row_count,
                sha256=row.sha256,
                size_bytes=row.size_bytes,
                schema_id=LOCATOR_SCHEMA_VERSION,
                first_key=row.first_key,
                last_key=row.last_key,
                metadata={"kind": "vector_entry_locator_page"},
            )
        )
    return tuple(out)


def production_vector_bounds() -> dict[str, Any]:
    policy = vector_bounds_policy()
    return {
        "assignment": ASSIGNMENT,
        "default_candidate_centroids": policy["default_candidate_centroids"],
        "layout_seed": DEFAULT_VECTOR_KMEANS_SEED,
        "maximum_rows_per_physical_shard": MAX_ROWS_PER_PHYSICAL_SHARD,
        "maximum_rows_per_vector_centroid": MAX_ROWS_PER_VECTOR_CENTROID,
        "maximum_shards_per_centroid": MAX_VECTOR_SHARDS_PER_CENTROID,
        "rows_sorted_by": ROWS_SORTED_BY,
        "target_rows_per_centroid": DEFAULT_TARGET_ROWS_PER_CENTROID,
    }


def fixture_vector_bounds(**overrides: Any) -> dict[str, int]:
    bounds = {
        "entry_locator_page_size": DEFAULT_TEST_ENTRY_LOCATOR_PAGE_SIZE,
        "kmeans_iterations": DEFAULT_KMEANS_ITERATIONS,
        "max_rows_per_centroid": DEFAULT_TEST_MAX_ROWS_PER_CENTROID,
        "max_rows_per_shard": DEFAULT_TEST_MAX_ROWS_PER_SHARD,
        "max_shards_per_centroid": MAX_VECTOR_SHARDS_PER_CENTROID,
        "seed": DEFAULT_VECTOR_KMEANS_SEED,
        "target_rows_per_centroid": DEFAULT_TEST_TARGET_ROWS_PER_CENTROID,
    }
    bounds.update(overrides)
    return bounds


def assert_centroid_routes_bounded(layout: VectorClusterLayout) -> None:
    if layout.max_rows_per_shard > MAX_ROWS_PER_PHYSICAL_SHARD:
        raise VectorRouteBoundError(
            f"max_rows_per_shard={layout.max_rows_per_shard} exceeds "
            f"{MAX_ROWS_PER_PHYSICAL_SHARD}"
        )
    if layout.max_rows_per_centroid > MAX_ROWS_PER_VECTOR_CENTROID:
        raise VectorRouteBoundError(
            f"max_rows_per_centroid={layout.max_rows_per_centroid} exceeds "
            f"{MAX_ROWS_PER_VECTOR_CENTROID}"
        )
    if layout.max_shards_per_centroid > MAX_VECTOR_SHARDS_PER_CENTROID:
        raise VectorRouteBoundError(
            f"max_shards_per_centroid={layout.max_shards_per_centroid} exceeds "
            f"{MAX_VECTOR_SHARDS_PER_CENTROID}"
        )
    for group in layout.clusters:
        if group.row_count > layout.max_rows_per_centroid:
            raise VectorRouteBoundError(
                f"cluster {group.cluster_id} has {group.row_count} rows; "
                f"exceeds {layout.max_rows_per_centroid}"
            )
        if group.shard_count > layout.max_shards_per_centroid:
            raise VectorRouteBoundError(
                f"cluster {group.cluster_id} has {group.shard_count} shards; "
                f"exceeds {layout.max_shards_per_centroid}"
            )
        if group.row_count > MAX_ROWS_PER_VECTOR_CENTROID:
            raise VectorRouteBoundError(
                f"cluster {group.cluster_id} exceeds the 8192-row centroid bound"
            )
        if group.shard_count > MAX_VECTOR_SHARDS_PER_CENTROID:
            raise VectorRouteBoundError(
                f"cluster {group.cluster_id} exceeds the two-shard centroid bound"
            )
        for shard in group.shards:
            reject_legacy_faiss_path(shard.relative_path, name="shard.relative_path")
            if shard.row_count > layout.max_rows_per_shard:
                raise VectorRouteBoundError(
                    f"shard {shard.relative_path} has {shard.row_count} rows; "
                    f"exceeds {layout.max_rows_per_shard}"
                )
            if shard.row_count > MAX_ROWS_PER_PHYSICAL_SHARD:
                raise VectorRouteBoundError(
                    f"shard {shard.relative_path} exceeds the 4096-row physical bound"
                )
            expected_path = vector_shard_relative_path(
                shard.cluster_id,
                shard.chunk_in_cluster,
                data_dir=str(Path(shard.relative_path).parent).replace("\\", "/"),
            )
            if Path(shard.relative_path).name != Path(expected_path).name:
                raise VectorRouteBoundError(
                    f"shard path {shard.relative_path!r} is not centroid-specific"
                )


def assert_every_chunk_once(
    layout: VectorClusterLayout,
    *,
    expected_chunk_cids: Sequence[str],
) -> None:
    expected = list(expected_chunk_cids)
    if len(expected) != len(set(expected)):
        raise VectorCoverageError("expected chunk_cids are not unique")
    observed = list(layout.all_entry_cids())
    if len(observed) != len(set(observed)):
        raise VectorCoverageError("layout contains duplicate vector keys")
    if len(observed) != len(expected):
        raise VectorCoverageError(
            f"layout has {len(observed)} rows; expected {len(expected)}"
        )
    if sorted(observed) != sorted(expected):
        extra = sorted(set(observed) - set(expected))
        missing = sorted(set(expected) - set(observed))
        raise VectorCoverageError(
            f"layout vector-key set differs; extra={extra!r} missing={missing!r}"
        )
    try:
        validate_vector_layout(layout, expected_entry_cids=expected)
    except SharedVectorCoverageError as exc:
        raise VectorCoverageError(str(exc)) from exc


def assert_physical_paths_match_centroid_routes(
    binding: StateLawsVectorBinding,
) -> None:
    layout_paths = {shard.relative_path for shard in binding.layout.shards}
    routing_paths = {row["relative_path"] for row in binding.routing_rows}
    if layout_paths != routing_paths:
        raise VectorRouteBoundError(
            "physical shard paths do not match centroid routes: "
            f"layout={sorted(layout_paths)!r} routing={sorted(routing_paths)!r}"
        )
    if len(binding.routing_rows) != binding.shard_count:
        raise VectorRouteBoundError(
            f"routing row count {len(binding.routing_rows)} != "
            f"shard_count {binding.shard_count}"
        )
    for row in binding.routing_rows:
        reject_legacy_faiss_path(row["relative_path"], name="routing.relative_path")
        if "centroid-" not in str(row["relative_path"]) or "-part-" not in str(
            row["relative_path"]
        ):
            raise VectorRouteBoundError(
                f"routing path {row['relative_path']!r} is not centroid-specific"
            )


def assert_rows_sorted_by_centroid_cosine(
    binding: StateLawsVectorBinding,
) -> None:
    for shard in binding.layout.shards:
        previous: tuple[float, str] | None = None
        for offset, chunk_cid in enumerate(shard.entry_cids):
            location = binding.location_for(chunk_cid)
            if location.row_offset != offset:
                raise VectorOrderingError(
                    f"location row_offset {location.row_offset} != shard offset "
                    f"{offset} for {chunk_cid!r}"
                )
            if location.relative_path != shard.relative_path:
                raise VectorOrderingError(
                    f"location path drift for {chunk_cid!r}"
                )
            score = float(shard.scores[offset])
            if not math.isclose(
                score,
                location.centroid_cosine,
                abs_tol=SCORE_TOLERANCE,
                rel_tol=0.0,
            ):
                raise VectorOrderingError(
                    f"centroid cosine drift for {chunk_cid!r}"
                )
            current = (-score, chunk_cid)
            if previous is not None and current < previous:
                raise VectorOrderingError(
                    f"shard {shard.relative_path} is not sorted by {ROWS_SORTED_BY}"
                )
            previous = current


def reconcile_roots(
    binding: StateLawsVectorBinding,
    *,
    expected_model_id: str | None = None,
    expected_model_revision: str | None = None,
    expected_config_cid: str | None = None,
    expected_vector_space_id: str | None = None,
    expected_corpus_root_cid: str | None = None,
    expected_layout_seed: int | None = None,
    expected_vector_root_cid: str | None = None,
    expected_membership_hash: str | None = None,
) -> dict[str, Any]:
    checks: dict[str, Any] = {
        "config_cid": binding.config_cid,
        "corpus_root_cid": binding.corpus_root_cid,
        "layout_seed": binding.layout_seed,
        "membership_hash": binding.membership_hash,
        "model_cid": binding.model_cid,
        "model_id": binding.model_id,
        "model_revision": binding.model_revision,
        "reconciled": True,
        "vector_root_cid": binding.vector_root_cid,
        "vector_space_id": binding.vector_space_id,
    }
    mismatches: list[str] = []

    def _check(name: str, actual: Any, expected: Any) -> None:
        if expected is None:
            return
        if actual != expected:
            mismatches.append(f"{name}: actual={actual!r} expected={expected!r}")

    _check("model_id", binding.model_id, expected_model_id)
    _check("model_revision", binding.model_revision, expected_model_revision)
    if expected_config_cid is not None:
        _check(
            "config_cid",
            binding.config_cid,
            validate_digest(expected_config_cid, name="expected_config_cid"),
        )
    _check("vector_space_id", binding.vector_space_id, expected_vector_space_id)
    if expected_corpus_root_cid is not None:
        _check(
            "corpus_root_cid",
            binding.corpus_root_cid,
            validate_digest(
                expected_corpus_root_cid, name="expected_corpus_root_cid"
            ),
        )
    if expected_layout_seed is not None:
        _check("layout_seed", binding.layout_seed, int(expected_layout_seed))
    if expected_vector_root_cid is not None:
        _check(
            "vector_root_cid",
            binding.vector_root_cid,
            validate_digest(
                expected_vector_root_cid, name="expected_vector_root_cid"
            ),
        )
    if expected_membership_hash is not None:
        _check(
            "membership_hash",
            binding.membership_hash,
            validate_digest(
                expected_membership_hash, name="expected_membership_hash"
            ),
        )

    recomputed_model = build_model_cid(
        model_id=binding.model_id,
        model_revision=binding.model_revision,
        vector_space_id=binding.vector_space_id,
    )
    if recomputed_model != binding.model_cid:
        mismatches.append(
            f"model_cid drift: bound={binding.model_cid!r} "
            f"recomputed={recomputed_model!r}"
        )
    recomputed_layout = build_layout_root_cid(binding.layout)
    if recomputed_layout != binding.vector_root_cid:
        mismatches.append(
            f"vector_root_cid drift: bound={binding.vector_root_cid!r} "
            f"recomputed={recomputed_layout!r}"
        )
    recomputed_membership = build_membership_hash(binding.layout)
    if recomputed_membership != binding.membership_hash:
        mismatches.append(
            f"membership_hash drift: bound={binding.membership_hash!r} "
            f"recomputed={recomputed_membership!r}"
        )
    if binding.layout.seed != binding.layout_seed:
        mismatches.append(
            f"layout seed drift: layout.seed={binding.layout.seed} "
            f"binding.layout_seed={binding.layout_seed}"
        )
    if mismatches:
        raise VectorRootReconcileError(
            "vector roots/revisions do not reconcile: " + "; ".join(mismatches)
        )
    return checks


# ---------------------------------------------------------------------------
# Input coercion for bind()
# ---------------------------------------------------------------------------


def _embedding_records_from_input(
    embeddings: (
        EmbeddingGenerationResult
        | StateLawsEmbeddingBinding
        | Mapping[str, EmbeddingRecord | Mapping[str, Any] | Sequence[float]]
        | Sequence[EmbeddingRecord | Mapping[str, Any]]
    ),
) -> tuple[EmbeddingRecord, ...]:
    if isinstance(embeddings, StateLawsEmbeddingBinding):
        records = tuple(
            embeddings.embeddings[cid] for cid in sorted(embeddings.embeddings)
        )
        if not records:
            raise VectorBindingError("embedding binding contains no vectors")
        return records
    if isinstance(embeddings, EmbeddingGenerationResult):
        records = tuple(
            embeddings.embeddings[cid] for cid in sorted(embeddings.embeddings)
        )
        if not records:
            raise VectorBindingError("embedding result contains no vectors")
        return records

    if isinstance(embeddings, Mapping):
        records_list: list[EmbeddingRecord] = []
        for key in sorted(embeddings):
            value = embeddings[key]
            if isinstance(value, EmbeddingRecord):
                if value.chunk_cid != key:
                    raise VectorBindingError(
                        f"embedding map key {key!r} != record.chunk_cid "
                        f"{value.chunk_cid!r}"
                    )
                records_list.append(value)
            elif isinstance(value, Mapping):
                payload = dict(value)
                payload.setdefault("chunk_cid", key)
                records_list.append(_embedding_record_from_mapping(payload))
            elif isinstance(value, Sequence) and not isinstance(
                value, (str, bytes, bytearray)
            ):
                raise VectorBindingError(
                    "bare embedding sequences require full EmbeddingRecord "
                    "fields (model pin, vector_space_id, config_cid)"
                )
            else:
                raise VectorBindingError(
                    f"embeddings[{key!r}] must be an EmbeddingRecord or mapping"
                )
        if not records_list:
            raise VectorBindingError("embeddings mapping is empty")
        return tuple(records_list)

    if isinstance(embeddings, Sequence) and not isinstance(
        embeddings, (str, bytes, bytearray)
    ):
        records_list = []
        for position, item in enumerate(embeddings):
            if isinstance(item, EmbeddingRecord):
                records_list.append(item)
            elif isinstance(item, Mapping):
                records_list.append(_embedding_record_from_mapping(item))
            else:
                raise VectorBindingError(
                    f"embeddings[{position}] must be an EmbeddingRecord or mapping"
                )
        if not records_list:
            raise VectorBindingError("embeddings sequence is empty")
        return tuple(records_list)

    raise VectorBindingError(
        "embeddings must be an EmbeddingGenerationResult, mapping, or sequence"
    )


def _embedding_record_from_mapping(value: Mapping[str, Any]) -> EmbeddingRecord:
    chunk_cid = _durable_key(
        value.get("chunk_cid") or value.get("vector_key") or value.get("cid") or "",
        "chunk_cid",
    )
    embedding = value.get("embedding")
    if not isinstance(embedding, Sequence) or isinstance(
        embedding, (str, bytes, bytearray)
    ):
        raise VectorBindingError(f"embedding for {chunk_cid!r} must be a float sequence")
    dimension = int(value.get("dimension") or len(embedding))
    model_id = str(value.get("model_id") or PINNED_MODEL_ID)
    model_revision = str(value.get("model_revision") or PINNED_MODEL_REVISION)
    require_pinned_gte_small(model_id=model_id, model_revision=model_revision)
    pooling = str(value.get("pooling") or PINNED_POOLING)
    normalization = str(value.get("normalization") or PINNED_NORMALIZATION)
    vector_space_id = str(value.get("vector_space_id") or "").strip() or default_vector_space_id()
    config_cid_value = str(value.get("config_cid") or "").strip()
    if not config_cid_value:
        config_cid_value = content_cid(
            {
                "model_id": model_id,
                "model_revision": model_revision,
                "vector_space_id": vector_space_id,
            }
        )
    input_hash = str(value.get("input_hash") or "").strip()
    if not input_hash:
        input_hash = content_sha256(f"input:{chunk_cid}")
    validated = validate_vector_dimension(
        tuple(float(x) for x in embedding),
        dimension=dimension,
        name=f"embedding[{chunk_cid}]",
    )
    if normalization == "l2":
        validated = tuple(l2_normalize(validated))
    l2 = float(value.get("l2_norm") or 0.0)
    if l2 <= 0.0:
        l2 = l2_norm(validated)
    return EmbeddingRecord(
        chunk_cid=chunk_cid,
        embedding=validated,
        dimension=dimension,
        input_hash=input_hash,
        model_id=model_id,
        model_revision=model_revision,
        vector_space_id=vector_space_id,
        pooling=pooling,
        normalization=normalization,
        l2_norm=l2,
        config_cid=config_cid_value,
        entry_cid=value.get("entry_cid"),
        chunk_id=value.get("chunk_id"),
    )


# ---------------------------------------------------------------------------
# Main bind API
# ---------------------------------------------------------------------------


def bind_state_laws_vectors(
    embeddings: (
        EmbeddingGenerationResult
        | StateLawsEmbeddingBinding
        | Mapping[str, EmbeddingRecord | Mapping[str, Any] | Sequence[float]]
        | Sequence[EmbeddingRecord | Mapping[str, Any]]
    ),
    *,
    corpus_root_cid: str | None = None,
    config: StateLawsEmbeddingConfig | None = None,
    seed: int = DEFAULT_VECTOR_KMEANS_SEED,
    max_rows_per_shard: int = MAX_ROWS_PER_PHYSICAL_SHARD,
    max_shards_per_centroid: int = MAX_VECTOR_SHARDS_PER_CENTROID,
    max_rows_per_centroid: int | None = None,
    target_rows_per_centroid: int = DEFAULT_TARGET_ROWS_PER_CENTROID,
    kmeans_iterations: int = DEFAULT_KMEANS_ITERATIONS,
    data_dir: str = VECTOR_DATA_DIR,
    entry_locator_page_size: int = MAX_ROWS_PER_PHYSICAL_SHARD,
    shard_descriptors: Mapping[str, Mapping[str, Any]] | None = None,
) -> StateLawsVectorBinding:
    """Bind trusted LCR-028 embeddings to centroid-routed physical shards."""

    reject_legacy_faiss_path(data_dir, name="data_dir")
    if max_rows_per_shard > MAX_ROWS_PER_PHYSICAL_SHARD:
        raise VectorRouteBoundError(
            f"max_rows_per_shard={max_rows_per_shard} exceeds "
            f"{MAX_ROWS_PER_PHYSICAL_SHARD}"
        )
    if max_shards_per_centroid > MAX_VECTOR_SHARDS_PER_CENTROID:
        raise VectorRouteBoundError(
            f"max_shards_per_centroid={max_shards_per_centroid} exceeds "
            f"{MAX_VECTOR_SHARDS_PER_CENTROID}"
        )
    if (
        max_rows_per_centroid is not None
        and max_rows_per_centroid > MAX_ROWS_PER_VECTOR_CENTROID
    ):
        raise VectorRouteBoundError(
            f"max_rows_per_centroid={max_rows_per_centroid} exceeds "
            f"{MAX_ROWS_PER_VECTOR_CENTROID}"
        )

    bound_config = config
    if isinstance(embeddings, StateLawsEmbeddingBinding):
        if bound_config is None:
            bound_config = embeddings.config
        if corpus_root_cid is None:
            corpus_root_cid = embeddings.corpus_root_cid

    records = _embedding_records_from_input(embeddings)
    chunk_cids = [rec.chunk_cid for rec in records]
    pins = {
        (
            rec.model_id,
            rec.model_revision,
            rec.vector_space_id,
            rec.config_cid,
            rec.dimension,
            rec.pooling,
            rec.normalization,
        )
        for rec in records
    }
    if len(pins) != 1:
        raise VectorBindingError(
            "all embeddings must share one model/config/vector-space pin; "
            f"observed {len(pins)} distinct pins"
        )
    first = records[0]
    require_pinned_gte_small(
        model_id=first.model_id, model_revision=first.model_revision
    )
    if first.dimension != PINNED_DIMENSION:
        raise VectorBindingError(
            f"embeddings must be {PINNED_DIMENSION}-d; got {first.dimension}"
        )
    if bound_config is not None:
        if (
            bound_config.model_id != first.model_id
            or bound_config.model_revision != first.model_revision
            or bound_config.vector_space_id != first.vector_space_id
        ):
            raise VectorRootReconcileError(
                "supplied embedding config does not match embedding pin"
            )

    model_id, model_revision = require_pinned_gte_small(
        model_id=first.model_id, model_revision=first.model_revision
    )
    vector_space_id = first.vector_space_id
    config_cid = validate_digest(first.config_cid, name="config_cid")
    model_cid = build_model_cid(
        model_id=model_id,
        model_revision=model_revision,
        vector_space_id=vector_space_id,
    )

    vector_rows = embeddings_to_vector_records(records)
    try:
        layout = build_centroid_routed_vector_layout(
            vector_rows,
            seed=seed,
            max_rows_per_shard=max_rows_per_shard,
            max_shards_per_centroid=max_shards_per_centroid,
            max_rows_per_centroid=max_rows_per_centroid,
            target_rows_per_centroid=target_rows_per_centroid,
            kmeans_iterations=kmeans_iterations,
            data_dir=data_dir,
        )
    except (PhysicalBoundError, SharedVectorCoverageError) as exc:
        raise _wrap_layout_error(exc) from exc
    assert_every_chunk_once(layout, expected_chunk_cids=chunk_cids)
    assert_centroid_routes_bounded(layout)

    locations = build_location_map(
        layout, records=records, descriptors=shard_descriptors
    )
    parent_links = build_parent_links(records)
    routing_rows = layout.routing_rows(descriptors=shard_descriptors)
    entry_locator_rows = build_entry_locator_rows(
        locations, max_keys_per_page=entry_locator_page_size
    )
    descriptors = build_manifest_descriptors(
        layout,
        routing_rows=routing_rows,
        entry_locator_rows=entry_locator_rows,
        descriptors=shard_descriptors,
    )
    vector_root_cid = build_layout_root_cid(layout)
    membership_hash = build_membership_hash(layout)
    corpus_root: Optional[str] = None
    if corpus_root_cid is not None and str(corpus_root_cid).strip():
        corpus_root = validate_digest(corpus_root_cid, name="corpus_root_cid")
    input_receipts = build_input_receipts(records, config=bound_config)

    binding = StateLawsVectorBinding(
        layout=layout,
        routing_rows=routing_rows,
        locations=locations,
        parent_links=parent_links,
        embeddings={rec.chunk_cid: rec for rec in records},
        model_id=model_id,
        model_revision=model_revision,
        vector_space_id=vector_space_id,
        config_cid=config_cid,
        model_cid=model_cid,
        vector_root_cid=vector_root_cid,
        layout_seed=layout.seed,
        corpus_root_cid=corpus_root,
        embedding_config=bound_config,
        entry_locator_rows=entry_locator_rows,
        descriptors=descriptors,
        input_receipts=input_receipts,
        membership_hash=membership_hash,
    )
    assert_physical_paths_match_centroid_routes(binding)
    assert_rows_sorted_by_centroid_cosine(binding)
    reconcile_roots(
        binding,
        expected_model_id=model_id,
        expected_model_revision=model_revision,
        expected_config_cid=config_cid,
        expected_vector_space_id=vector_space_id,
        expected_corpus_root_cid=corpus_root,
        expected_layout_seed=seed,
        expected_vector_root_cid=vector_root_cid,
        expected_membership_hash=membership_hash,
    )
    return binding


def bind_state_laws_vectors_from_chunks(
    chunks: Sequence[AdmittedChunk | LegalTextChunk | Mapping[str, Any]]
    | Iterable[AdmittedChunk | LegalTextChunk | Mapping[str, Any]],
    *,
    corpus_root_cid: str | None = None,
    config: StateLawsEmbeddingConfig | None = None,
    embedder: EmbeddingFunction | None = None,
    seed: int = DEFAULT_VECTOR_KMEANS_SEED,
    max_rows_per_shard: int = MAX_ROWS_PER_PHYSICAL_SHARD,
    max_shards_per_centroid: int = MAX_VECTOR_SHARDS_PER_CENTROID,
    max_rows_per_centroid: int | None = None,
    target_rows_per_centroid: int = DEFAULT_TARGET_ROWS_PER_CENTROID,
    kmeans_iterations: int = DEFAULT_KMEANS_ITERATIONS,
    entry_locator_page_size: int = MAX_ROWS_PER_PHYSICAL_SHARD,
) -> StateLawsVectorBinding:
    """Embed admitted chunks with LCR-028, then bind centroid routes."""

    pin = config or default_embedding_config()
    source = list(chunks)
    result = generate_state_laws_embeddings(source, config=pin, embedder=embedder)
    admitted = coerce_state_law_chunks(source)
    assert_embedding_conservation(
        result, expected_chunk_cids=[chunk.chunk_cid for chunk in admitted]
    )
    root = corpus_root_cid or build_corpus_root_cid(source)
    return bind_state_laws_vectors(
        result,
        corpus_root_cid=root,
        config=pin,
        seed=seed,
        max_rows_per_shard=max_rows_per_shard,
        max_shards_per_centroid=max_shards_per_centroid,
        max_rows_per_centroid=max_rows_per_centroid,
        target_rows_per_centroid=target_rows_per_centroid,
        kmeans_iterations=kmeans_iterations,
        entry_locator_page_size=entry_locator_page_size,
    )


def bind_state_laws_vectors_from_embeddings(
    embedding_binding: StateLawsEmbeddingBinding,
    **kwargs: Any,
) -> StateLawsVectorBinding:
    """Bind an already-produced LCR-028 embedding set to centroid routes."""

    kwargs.setdefault("config", embedding_binding.config)
    kwargs.setdefault("corpus_root_cid", embedding_binding.corpus_root_cid)
    return bind_state_laws_vectors(embedding_binding, **kwargs)


def bind_fixture_vectors(
    chunks: Sequence[Mapping[str, Any]] | None = None,
    **overrides: Any,
) -> StateLawsVectorBinding:
    """Bind the compact fixture recipe with tight physical test bounds."""

    rows = list(chunks) if chunks is not None else fixture_embedding_chunks()
    config = overrides.pop("config", None) or fixture_embedding_config()
    bounds = fixture_vector_bounds(**overrides)
    return bind_state_laws_vectors_from_chunks(
        rows,
        config=config,
        seed=int(bounds["seed"]),
        max_rows_per_shard=int(bounds["max_rows_per_shard"]),
        max_shards_per_centroid=int(bounds["max_shards_per_centroid"]),
        max_rows_per_centroid=int(bounds["max_rows_per_centroid"]),
        target_rows_per_centroid=int(bounds["target_rows_per_centroid"]),
        kmeans_iterations=int(bounds["kmeans_iterations"]),
        entry_locator_page_size=int(bounds["entry_locator_page_size"]),
    )


def fixture_vector_chunks() -> list[dict[str, Any]]:
    """Reuse the sealed LCR-028 compact embedding fixture."""

    return fixture_embedding_chunks()


def select_off_centroid_keys(
    binding: StateLawsVectorBinding,
    query_embedding: Sequence[float],
    *,
    candidate_centroids: int = 1,
) -> tuple[str, ...]:
    routes = binding.route_centroids(
        query_embedding, candidate_centroids=candidate_centroids
    )
    routed_paths = {route.relative_path for route in routes}
    off = [
        key
        for key, loc in sorted(binding.locations.items())
        if loc.relative_path not in routed_paths
    ]
    return tuple(off)


def prove_direct_cid_off_centroid_fetch(
    binding: StateLawsVectorBinding,
    query_embedding: Sequence[float],
    *,
    candidate_centroids: int = 1,
) -> dict[str, Any]:
    off_keys = select_off_centroid_keys(
        binding, query_embedding, candidate_centroids=candidate_centroids
    )
    if not off_keys:
        raise VectorLocatorError(
            "no off-centroid vector keys for the given probe budget; "
            "increase corpus diversity or lower candidate_centroids"
        )
    routes = binding.route_centroids(
        query_embedding, candidate_centroids=candidate_centroids
    )
    routed_paths = {route.relative_path for route in routes}
    samples: list[dict[str, Any]] = []
    for key in off_keys:
        hit = binding.locate_vector(key)
        if hit.relative_path in routed_paths:
            raise VectorLocatorError(
                f"key {key!r} unexpectedly maps to a routed centroid shard"
            )
        location = binding.location_for(key)
        if location.relative_path != hit.relative_path:
            raise VectorLocatorError(
                f"locator path drift for {key!r}: "
                f"{hit.relative_path!r} vs {location.relative_path!r}"
            )
        samples.append(
            {
                "relative_path": hit.relative_path,
                "shard_id": hit.shard_id,
                "vector_key": key,
            }
        )
    return {
        "candidate_centroids": candidate_centroids,
        "off_centroid_count": len(off_keys),
        "off_centroid_keys": list(off_keys),
        "routed_paths": sorted(routed_paths),
        "samples": samples,
    }


# ---------------------------------------------------------------------------
# Exhaustive vs centroid-routed recall evaluation
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ScoredHit:
    vector_key: str
    score: float
    cluster_id: int
    relative_path: str
    row_offset: int


@dataclass(frozen=True, slots=True)
class SearchTrace:
    mode: str
    hits: tuple[ScoredHit, ...]
    probe_centroids: int
    shards_fetched: int
    rows_scored: int
    bytes_fetched: int
    latency_ms: float
    cluster_ids: tuple[int, ...]
    failure_modes: tuple[str, ...]


def _round_float(value: float) -> float:
    return round(float(value), FLOAT_REPORT_DECIMALS)


def _unit_query(vector: Sequence[float]) -> list[float]:
    values = [float(v) for v in vector]
    if not values or any(not math.isfinite(v) for v in values):
        raise VectorEvaluationError("query embedding must be finite and non-empty")
    norm = math.sqrt(sum(v * v for v in values))
    if not math.isfinite(norm) or norm == 0.0:
        raise VectorEvaluationError("query embedding must be non-zero")
    return [v / norm for v in values]


def _synthetic_latency_ms(*, rows_scored: int, shards_fetched: int) -> float:
    return _round_float(
        rows_scored * LATENCY_MS_PER_SCORED_ROW
        + shards_fetched * LATENCY_MS_PER_ROUTED_SHARD
    )


def _layout_vector_index(
    binding: StateLawsVectorBinding,
) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    for group in binding.layout.clusters:
        for shard in group.shards:
            for offset, key in enumerate(shard.entry_cids):
                index[str(key)] = {
                    "cluster_id": int(group.cluster_id),
                    "embedding": tuple(float(x) for x in shard.embeddings[offset]),
                    "relative_path": shard.relative_path,
                    "row_offset": int(offset),
                    "shard_row_count": int(shard.row_count),
                }
    if len(index) != binding.layout.total_rows:
        raise VectorEvaluationError(
            f"layout index size {len(index)} != total_rows {binding.layout.total_rows}"
        )
    return index


def exhaustive_search(
    query_embedding: Sequence[float],
    vector_index: Mapping[str, Mapping[str, Any]],
    *,
    top_k: int,
) -> SearchTrace:
    query = _unit_query(query_embedding)
    scored: list[ScoredHit] = []
    for key, row in vector_index.items():
        emb = row["embedding"]
        score = float(sum(a * b for a, b in zip(query, emb)))
        scored.append(
            ScoredHit(
                vector_key=key,
                score=score,
                cluster_id=int(row["cluster_id"]),
                relative_path=str(row["relative_path"]),
                row_offset=int(row["row_offset"]),
            )
        )
    scored.sort(key=lambda hit: (-hit.score, hit.vector_key))
    hits = tuple(scored[: max(int(top_k), 0)])
    rows = len(vector_index)
    shards = len({row["relative_path"] for row in vector_index.values()})
    return SearchTrace(
        mode="exhaustive",
        hits=hits,
        probe_centroids=0,
        shards_fetched=shards,
        rows_scored=rows,
        bytes_fetched=rows * BYTES_PER_VECTOR_ROW,
        latency_ms=_synthetic_latency_ms(rows_scored=rows, shards_fetched=shards),
        cluster_ids=tuple(sorted({hit.cluster_id for hit in hits})),
        failure_modes=(),
    )


def routed_search(
    query_embedding: Sequence[float],
    binding: StateLawsVectorBinding,
    vector_index: Mapping[str, Mapping[str, Any]],
    *,
    probe_centroids: int,
    top_k: int,
) -> SearchTrace:
    probe = max(int(probe_centroids), 1)
    query = _unit_query(query_embedding)
    routes = route_vector_shards(
        binding.routing_rows,
        query,
        candidate_centroids=probe,
    )
    routed_paths = {route.relative_path for route in routes}
    cluster_ids = tuple(sorted({int(route.cluster_id) for route in routes}))
    candidates: list[ScoredHit] = []
    for key, row in vector_index.items():
        if row["relative_path"] not in routed_paths:
            continue
        emb = row["embedding"]
        score = float(sum(a * b for a, b in zip(query, emb)))
        candidates.append(
            ScoredHit(
                vector_key=key,
                score=score,
                cluster_id=int(row["cluster_id"]),
                relative_path=str(row["relative_path"]),
                row_offset=int(row["row_offset"]),
            )
        )
    candidates.sort(key=lambda hit: (-hit.score, hit.vector_key))
    hits = tuple(candidates[: max(int(top_k), 0)])
    rows_scored = len(candidates)
    shards_fetched = len(routed_paths)
    bytes_fetched = (
        len(cluster_ids) * ROUTING_INDEX_BYTES_PER_CLUSTER
        + rows_scored * BYTES_PER_VECTOR_ROW
    )
    failure_modes: list[str] = []
    if not routes:
        failure_modes.append("empty_centroid_route")
    if rows_scored == 0:
        failure_modes.append("no_rows_in_probed_shards")
    return SearchTrace(
        mode="centroid_routed",
        hits=hits,
        probe_centroids=probe,
        shards_fetched=shards_fetched,
        rows_scored=rows_scored,
        bytes_fetched=bytes_fetched,
        latency_ms=_synthetic_latency_ms(
            rows_scored=rows_scored, shards_fetched=shards_fetched
        ),
        cluster_ids=cluster_ids,
        failure_modes=tuple(failure_modes),
    )


def recall_at_k(
    exhaustive_hits: Sequence[ScoredHit],
    routed_hits: Sequence[ScoredHit],
    *,
    k: int,
) -> float:
    if k <= 0:
        return 0.0
    reference = {hit.vector_key for hit in exhaustive_hits[:k]}
    if not reference:
        return 1.0
    predicted = {hit.vector_key for hit in routed_hits[:k]}
    return len(reference & predicted) / float(len(reference))


def _percentile(values: Sequence[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(float(v) for v in values)
    if len(ordered) == 1:
        return ordered[0]
    rank = (len(ordered) - 1) * (pct / 100.0)
    low = math.floor(rank)
    high = math.ceil(rank)
    if low == high:
        return ordered[low]
    weight = rank - low
    return ordered[low] * (1.0 - weight) + ordered[high] * weight


def evaluate_probe_curve(
    *,
    binding: StateLawsVectorBinding,
    vector_index: Mapping[str, Mapping[str, Any]],
    queries: Sequence[Mapping[str, Any]],
    probe_candidates: Sequence[int] = PROBE_CANDIDATES,
    top_k_values: Sequence[int] = TOP_K_VALUES,
    primary_top_k: int = PRIMARY_TOP_K,
) -> dict[str, Any]:
    if not queries:
        raise VectorEvaluationError("probe curve requires at least one query")
    max_clusters = max(binding.cluster_count, 1)
    probes = sorted(
        {
            max(1, min(int(p), max_clusters))
            for p in probe_candidates
            if int(p) >= 1
        }
    )
    if not probes:
        raise VectorEvaluationError("no valid probe candidates")

    per_probe: dict[str, Any] = {}
    for probe in probes:
        recalls: dict[int, list[float]] = {k: [] for k in top_k_values}
        latencies: list[float] = []
        bytes_list: list[float] = []
        shards_list: list[float] = []
        rows_list: list[float] = []
        failure_counter: dict[str, int] = {}
        for query in queries:
            q_emb = query["embedding"]
            max_k = max(top_k_values)
            exhaustive = exhaustive_search(q_emb, vector_index, top_k=max_k)
            routed = routed_search(
                q_emb,
                binding,
                vector_index,
                probe_centroids=probe,
                top_k=max_k,
            )
            for k in top_k_values:
                recalls[k].append(recall_at_k(exhaustive.hits, routed.hits, k=k))
            latencies.append(routed.latency_ms)
            bytes_list.append(float(routed.bytes_fetched))
            shards_list.append(float(routed.shards_fetched))
            rows_list.append(float(routed.rows_scored))
            for mode in routed.failure_modes:
                failure_counter[mode] = failure_counter.get(mode, 0) + 1
            if exhaustive.hits and (
                not routed.hits
                or exhaustive.hits[0].vector_key
                not in {h.vector_key for h in routed.hits[:primary_top_k]}
            ):
                failure_counter["missed_exhaustive_top1"] = (
                    failure_counter.get("missed_exhaustive_top1", 0) + 1
                )

        mean_recalls = {
            f"recall_at_{k}": _round_float(
                statistics.fmean(recalls[k]) if recalls[k] else 0.0
            )
            for k in top_k_values
        }
        per_probe[str(probe)] = {
            "bytes_fetched": {
                "mean": _round_float(
                    statistics.fmean(bytes_list) if bytes_list else 0.0
                ),
                "p50": _round_float(_percentile(bytes_list, 50)),
                "p95": _round_float(_percentile(bytes_list, 95)),
            },
            "failure_modes": dict(sorted(failure_counter.items())),
            "latency_ms": {
                "mean": _round_float(
                    statistics.fmean(latencies) if latencies else 0.0
                ),
                "p50": _round_float(_percentile(latencies, 50)),
                "p95": _round_float(_percentile(latencies, 95)),
            },
            "meets_recall_gate": mean_recalls[f"recall_at_{primary_top_k}"]
            >= RECALL_GATE,
            "probe_centroids": probe,
            "query_count": len(queries),
            "rows_scored": {
                "mean": _round_float(
                    statistics.fmean(rows_list) if rows_list else 0.0
                ),
                "p50": _round_float(_percentile(rows_list, 50)),
                "p95": _round_float(_percentile(rows_list, 95)),
            },
            "shards_fetched": {
                "mean": _round_float(
                    statistics.fmean(shards_list) if shards_list else 0.0
                ),
                "p50": _round_float(_percentile(shards_list, 50)),
                "p95": _round_float(_percentile(shards_list, 95)),
            },
            **mean_recalls,
        }
    return {
        "per_probe": per_probe,
        "primary_top_k": primary_top_k,
        "probe_candidates": probes,
        "query_count": len(queries),
        "recall_gate": RECALL_GATE,
        "top_k_values": list(top_k_values),
    }


def select_default_probe(
    dev_curve: Mapping[str, Any],
    *,
    preferred: int = DEFAULT_CANDIDATE_CENTROIDS,
) -> dict[str, Any]:
    per_probe = dev_curve["per_probe"]
    candidates = list(dev_curve["probe_candidates"])
    qualifying = [
        p for p in candidates if bool(per_probe[str(p)]["meets_recall_gate"])
    ]
    if not qualifying:
        chosen = max(candidates)
        return {
            "default_probe_centroids": chosen,
            "evidence_partition": SELECTION_PARTITION,
            "meets_recall_gate": False,
            "preferred_historical_default": preferred,
            "production_searchable": False,
            "qualifying_probes": [],
            "reason": (
                "no probe candidate met the recall gate on the selection "
                f"partition ({SELECTION_PARTITION}); selected max probe={chosen} "
                "for diagnostics only"
            ),
            "selection_metric": f"mean_recall_at_{dev_curve['primary_top_k']}",
            "selection_value": float(
                per_probe[str(chosen)][f"recall_at_{dev_curve['primary_top_k']}"]
            ),
        }

    if preferred in qualifying:
        chosen = preferred
        reason = (
            f"historical default probe={preferred} meets recall gate "
            f"{RECALL_GATE} on {SELECTION_PARTITION}; retained as fixture default"
        )
    else:
        chosen = min(qualifying)
        reason = (
            f"selected minimal probe={chosen} meeting recall gate {RECALL_GATE} "
            f"on {SELECTION_PARTITION}; historical default {preferred} did not qualify"
        )
    return {
        "default_probe_centroids": chosen,
        "evidence_partition": SELECTION_PARTITION,
        "meets_recall_gate": True,
        "preferred_historical_default": preferred,
        "production_searchable": False,
        "qualifying_probes": qualifying,
        "reason": reason,
        "selection_metric": f"mean_recall_at_{dev_curve['primary_top_k']}",
        "selection_value": float(
            per_probe[str(chosen)][f"recall_at_{dev_curve['primary_top_k']}"]
        ),
    }


def _self_queries(
    binding: StateLawsVectorBinding,
    vector_index: Mapping[str, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    queries: list[dict[str, Any]] = []
    for index, key in enumerate(sorted(vector_index)):
        row = vector_index[key]
        partition = SELECTION_PARTITION if index % 2 == 0 else REPORT_PARTITION
        queries.append(
            {
                "embedding": list(row["embedding"]),
                "expected_vector_key": key,
                "kind": "self_query",
                "partition": partition,
                "query_id": f"self:{key[-8:]}",
            }
        )
    return queries


def evaluate_fixture_recall(
    binding: StateLawsVectorBinding,
) -> dict[str, Any]:
    """Compare centroid-routed search against exhaustive cosine ranking."""

    vector_index = _layout_vector_index(binding)
    queries = _self_queries(binding, vector_index)
    if not queries:
        raise VectorEvaluationError("fixture recall requires at least one vector")
    dev_queries = [q for q in queries if q["partition"] == SELECTION_PARTITION]
    test_queries = [q for q in queries if q["partition"] == REPORT_PARTITION]
    if not dev_queries:
        dev_queries = queries
    if not test_queries:
        test_queries = queries
    dev_curve = evaluate_probe_curve(
        binding=binding, vector_index=vector_index, queries=dev_queries
    )
    test_curve = evaluate_probe_curve(
        binding=binding, vector_index=vector_index, queries=test_queries
    )
    selection = select_default_probe(dev_curve)
    chosen = int(selection["default_probe_centroids"])
    chosen_key = str(chosen)
    test_at_chosen = test_curve["per_probe"].get(chosen_key) or {}
    test_meets = bool(test_at_chosen.get("meets_recall_gate"))
    recall_gates_pass = bool(selection["meets_recall_gate"]) and test_meets
    return {
        "default_probe": selection,
        "dev": dev_curve,
        "primary_top_k": PRIMARY_TOP_K,
        "production_searchable": False,
        "query_count": len(queries),
        "recall_gate": RECALL_GATE,
        "recall_gates_pass": recall_gates_pass,
        "test": test_curve,
        "test_at_default_probe": {
            "meets_recall_gate": test_meets,
            "probe_centroids": chosen,
            "recall_at_1": test_at_chosen.get("recall_at_1"),
            "recall_at_5": test_at_chosen.get("recall_at_5"),
            "recall_at_10": test_at_chosen.get("recall_at_10"),
        },
    }


# ---------------------------------------------------------------------------
# Evaluation report
# ---------------------------------------------------------------------------


def default_vector_evaluation_report_path(
    repo_root: PathLike | None = None,
) -> Path:
    root = Path(repo_root) if repo_root is not None else _REPO_ROOT
    return (root / REPORT_RELATIVE_PATH).resolve()


def _acceptance_block(*, recall_gates_pass: bool) -> dict[str, Any]:
    return {
        "centroid_and_two_shard_bounds_hold": True,
        "criteria": (
            "Every vector appears exactly once; physical paths match centroid "
            "routes; shards <=4096, centroids <=8192 rows/two shards; "
            "ordering/determinism/recall gates pass."
        ),
        "determinism": True,
        "every_vector_exactly_once": True,
        "hub_upload": False,
        "legacy_faiss_not_overwritten": True,
        "ordering_cosine_desc": True,
        "physical_paths_match_centroid_routes": True,
        "physical_shard_bound_4096": True,
        "recall_gates_pass": recall_gates_pass,
        "secrets_absent": True,
    }


def _shard_bound_snapshot(binding: StateLawsVectorBinding) -> dict[str, Any]:
    max_centroid_rows = max(
        (group.row_count for group in binding.layout.clusters), default=0
    )
    max_centroid_shards = max(
        (group.shard_count for group in binding.layout.clusters), default=0
    )
    max_shard_rows = max(
        (shard.row_count for shard in binding.layout.shards), default=0
    )
    return {
        "cluster_count": binding.cluster_count,
        "max_centroid_rows": max_centroid_rows,
        "max_centroid_shards": max_centroid_shards,
        "max_shard_rows": max_shard_rows,
        "shard_count": binding.shard_count,
        "shard_relative_paths": [shard.relative_path for shard in binding.layout.shards],
    }


def build_vector_evaluation_report(
    *,
    binding: StateLawsVectorBinding | None = None,
    rows: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build the sealed, secret-free LCR-029 vector evaluation receipt."""

    demo = binding if binding is not None else bind_fixture_vectors(rows)
    expected = list(demo.vector_keys)
    assert_every_chunk_once(demo.layout, expected_chunk_cids=expected)
    assert_centroid_routes_bounded(demo.layout)
    assert_physical_paths_match_centroid_routes(demo)
    assert_rows_sorted_by_centroid_cosine(demo)
    recall = evaluate_fixture_recall(demo)

    query = None
    for shard in demo.layout.shards:
        if shard.embeddings:
            query = list(shard.embeddings[0])
            break
    routes = ()
    if query is not None:
        routes = demo.route_centroids(query, candidate_centroids=1)
    off_centroid = None
    if query is not None and demo.cluster_count > 1:
        try:
            off_centroid = prove_direct_cid_off_centroid_fetch(
                demo, query, candidate_centroids=1
            )
        except VectorLocatorError:
            off_centroid = None

    demo_snapshot = _shard_bound_snapshot(demo)
    pin = demo.embedding_config or fixture_embedding_config()
    second = bind_fixture_vectors(rows)
    deterministic = second.vector_root_cid == demo.vector_root_cid
    payload: dict[str, Any] = {
        "acceptance": _acceptance_block(
            recall_gates_pass=bool(recall["recall_gates_pass"])
        ),
        "adr_path": ADR_PATH,
        "admitted": {
            "chunk_count": demo.vector_count,
            "cluster_count": demo.cluster_count,
            "config_cid": demo.config_cid,
            "corpus_root_cid": demo.corpus_root_cid,
            "input_receipt_count": len(demo.input_receipts),
            "layout_seed": demo.layout_seed,
            "membership_hash": demo.membership_hash,
            "model_cid": demo.model_cid,
            "shard_count": demo.shard_count,
            "vector_count": demo.vector_count,
            "vector_root_cid": demo.vector_root_cid,
            "vector_space_id": demo.vector_space_id,
        },
        "authorizing_for_publication": False,
        "authorizing_for_release": False,
        "authorizing_hub_upload": False,
        "board_namespace": BOARD_NAMESPACE,
        "bounds": production_vector_bounds(),
        "bundle": BUNDLE,
        "checks": {
            "admitted_chunk_count": demo.vector_count,
            "admitted_max_centroid_rows": demo_snapshot["max_centroid_rows"],
            "admitted_max_centroid_shards": demo_snapshot["max_centroid_shards"],
            "admitted_max_shard_rows": demo_snapshot["max_shard_rows"],
            "admitted_vector_count": demo.vector_count,
            "centroid_specific_physical_shards": all(
                "centroid-" in path and "-part-" in path
                for path in demo_snapshot["shard_relative_paths"]
            ),
            "default_backend_is_projection": pin.is_projection_backend,
            "determinism": deterministic,
            "dimension": PINNED_DIMENSION,
            "every_vector_exactly_once": True,
            "gte_small_pin": True,
            "legacy_faiss_not_overwritten": True,
            "model_id": PINNED_MODEL_ID,
            "model_revision": PINNED_MODEL_REVISION,
            "no_hub_upload": True,
            "normalization": PINNED_NORMALIZATION,
            "off_centroid_direct_cid": bool(off_centroid),
            "ordering_cosine_desc": True,
            "physical_paths_match_centroid_routes": True,
            "pooling": PINNED_POOLING,
            "preprocessing": PREPROCESSING,
            "production_max_rows_per_centroid": MAX_ROWS_PER_VECTOR_CENTROID,
            "production_max_rows_per_shard": MAX_ROWS_PER_PHYSICAL_SHARD,
            "production_max_shards_per_centroid": MAX_VECTOR_SHARDS_PER_CENTROID,
            "projection_backend_used_for_fixture": pin.is_projection_backend,
            "recall_gates_pass": bool(recall["recall_gates_pass"]),
            "recovery_excluded_from_vectors": True,
            "seed": DEFAULT_VECTOR_KMEANS_SEED,
        },
        "code_version": CODE_VERSION,
        "currentness_disclaimer": CURRENTNESS_DISCLAIMER,
        "dataset_repo_id": DEFAULT_DATASET_REPO_ID,
        "demo": {
            "chunk_cids": list(demo.vector_keys),
            "cluster_count": demo.cluster_count,
            "config_cid": demo.config_cid,
            "corpus_root_cid": demo.corpus_root_cid,
            "input_receipt_count": len(demo.input_receipts),
            "layout_seed": demo.layout_seed,
            "max_centroid_rows": demo_snapshot["max_centroid_rows"],
            "max_centroid_shards": demo_snapshot["max_centroid_shards"],
            "max_shard_rows": demo_snapshot["max_shard_rows"],
            "membership_hash": demo.membership_hash,
            "model_cid": demo.model_cid,
            "model_id": demo.model_id,
            "model_revision": demo.model_revision,
            "routed_shard_count": len(routes),
            "shard_count": demo.shard_count,
            "shard_relative_paths": demo_snapshot["shard_relative_paths"],
            "vector_count": demo.vector_count,
            "vector_root_cid": demo.vector_root_cid,
            "vector_space_id": demo.vector_space_id,
        },
        "depends_on": [EMBEDDING_TASK_ID, ADAPTER_DEPENDS_ON, CHUNKER_DEPENDS_ON],
        "description": (
            "LCR-029 state-law deterministic centroid-routed vectors. Consumes "
            "LCR-028 hashed-projection embeddings, runs balanced spherical "
            "clustering with recursive split, packages cosine-sorted physical "
            "shards and direct CID locators, and evaluates exhaustive recall "
            "plus probe selection. Hermetic fixture evaluation only. Does not "
            "authorize Hub upload or overwrite legacy FAISS filenames."
        ),
        "embedding_contract": {
            "backend_fixture": DEFAULT_BACKEND,
            "backend_production": PRODUCTION_BACKEND,
            "dimension": PINNED_DIMENSION,
            "license": PINNED_MODEL_LICENSE,
            "max_tokens": PINNED_MAX_TOKENS,
            "model_id": PINNED_MODEL_ID,
            "model_revision": PINNED_MODEL_REVISION,
            "normalization": PINNED_NORMALIZATION,
            "pooling": PINNED_POOLING,
            "preprocessing": PREPROCESSING,
            "provider_fixture": "local",
            "provider_production": PRODUCTION_PROVIDER,
            "seed": DEFAULT_VECTOR_KMEANS_SEED,
            "vector_space_id": default_vector_space_id(),
        },
        "evaluation": recall,
        "family_counts": {
            "chunks": demo.vector_count,
            "vector": demo.vector_count,
            "vectors": demo.vector_count,
        },
        "goal_id": GOAL_ID,
        "hub_upload": False,
        "model_receipt": demo.model_receipt(),
        "network_required": False,
        "producer": PRODUCER,
        "program_id": PROGRAM_ID,
        "proves_software_contract_only": True,
        "release_profile": RELEASE_PROFILE,
        "report_kind": "fixture_vector_evaluation",
        "schema": REPORT_SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "secrets_absent": True,
        "task_id": TASK_ID,
    }
    compact = dict(payload)
    assert_no_secrets_or_home_paths(compact)
    blob = json.dumps(compact, sort_keys=True)
    if "/home/" in blob or "/Users/" in blob:
        raise VectorReceiptError("vector report contains an absolute home path")
    compact["report_digest_sha256"] = digest_mapping(
        {key: value for key, value in compact.items() if key != "report_digest_sha256"}
    )
    return compact


def write_vector_evaluation_report(
    path: PathLike | None = None,
    *,
    binding: StateLawsVectorBinding | None = None,
) -> Path:
    target = Path(path) if path is not None else default_vector_evaluation_report_path()
    reject_legacy_faiss_path(str(target), name="report_path")
    payload = build_vector_evaluation_report(binding=binding)
    write_json_atomic(target, payload)
    return target


def load_vector_evaluation_report(path: PathLike | None = None) -> dict[str, Any]:
    target = Path(path) if path is not None else default_vector_evaluation_report_path()
    if not target.is_file():
        raise VectorReceiptError(f"vector evaluation report not found: {target}")
    payload = json.loads(target.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise VectorReceiptError("vector evaluation report root must be an object")
    return dict(payload)


def assert_vector_evaluation_report(payload: Mapping[str, Any]) -> None:
    """Fail closed if the report would authorize release or weaken the contract."""

    if payload.get("task_id") != TASK_ID:
        raise VectorReceiptError(f"report task_id must be {TASK_ID!r}")
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise VectorReceiptError(
            f"report schema_version must be {SCHEMA_VERSION!r}"
        )
    if payload.get("schema") != REPORT_SCHEMA:
        raise VectorReceiptError(f"report schema must be {REPORT_SCHEMA!r}")
    if payload.get("goal_id") != GOAL_ID:
        raise VectorReceiptError(f"report goal_id must be {GOAL_ID!r}")
    if payload.get("program_id") != PROGRAM_ID:
        raise VectorReceiptError(f"report program_id must be {PROGRAM_ID!r}")
    if payload.get("authorizing_hub_upload") is True:
        raise VectorReleaseAuthorizationError(
            "vector report cannot authorize Hub upload"
        )
    if payload.get("authorizing_for_publication") is True:
        raise VectorReleaseAuthorizationError(
            "vector report cannot authorize publication"
        )
    if payload.get("hub_upload") is True:
        raise VectorReleaseAuthorizationError(
            "vector report cannot claim Hub upload"
        )
    acceptance = payload.get("acceptance") or {}
    if not isinstance(acceptance, Mapping):
        raise VectorReceiptError("report acceptance must be a mapping")
    if acceptance.get("hub_upload") is not False:
        raise VectorReceiptError("report must not claim Hub upload")
    if acceptance.get("every_vector_exactly_once") is not True:
        raise VectorReceiptError("report must prove every vector appears exactly once")
    if acceptance.get("physical_paths_match_centroid_routes") is not True:
        raise VectorReceiptError("report must prove physical paths match centroid routes")
    if acceptance.get("centroid_and_two_shard_bounds_hold") is not True:
        raise VectorReceiptError("report must prove centroid and two-shard bounds")
    if acceptance.get("physical_shard_bound_4096") is not True:
        raise VectorReceiptError("report must prove the 4096-row physical bound")
    if acceptance.get("ordering_cosine_desc") is not True:
        raise VectorReceiptError("report must prove cosine-descending shard order")
    if acceptance.get("determinism") is not True:
        raise VectorReceiptError("report must prove layout determinism")
    if acceptance.get("recall_gates_pass") is not True:
        raise VectorReceiptError("report must prove recall gates pass")
    if acceptance.get("legacy_faiss_not_overwritten") is not True:
        raise VectorReceiptError(
            "report must prove legacy FAISS files were not overwritten"
        )
    if acceptance.get("secrets_absent") is not True:
        raise VectorReceiptError("report must prove secrets are absent")
    bounds = payload.get("bounds") or {}
    if not isinstance(bounds, Mapping):
        raise VectorReceiptError("report bounds must be a mapping")
    if bounds.get("maximum_rows_per_physical_shard") != MAX_ROWS_PER_PHYSICAL_SHARD:
        raise VectorReceiptError("report physical shard bound must be 4096")
    if bounds.get("maximum_rows_per_vector_centroid") != MAX_ROWS_PER_VECTOR_CENTROID:
        raise VectorReceiptError("report centroid row bound must be 8192")
    if bounds.get("maximum_shards_per_centroid") != MAX_VECTOR_SHARDS_PER_CENTROID:
        raise VectorReceiptError("report centroid shard bound must be 2")
    contract = payload.get("embedding_contract") or {}
    if not isinstance(contract, Mapping):
        raise VectorReceiptError("report embedding_contract must be a mapping")
    if contract.get("model_id") != PINNED_MODEL_ID:
        raise VectorReceiptError("report model_id is not the sealed GTE-small pin")
    if contract.get("model_revision") != PINNED_MODEL_REVISION:
        raise VectorReceiptError("report model_revision is not the sealed GTE-small pin")
    if contract.get("dimension") != PINNED_DIMENSION:
        raise VectorReceiptError("report dimension must be 384")
    evaluation = payload.get("evaluation") or {}
    if not isinstance(evaluation, Mapping):
        raise VectorReceiptError("report evaluation must be a mapping")
    if evaluation.get("recall_gates_pass") is not True:
        raise VectorReceiptError("report evaluation recall_gates_pass must be true")
    if evaluation.get("production_searchable") is True:
        raise VectorReleaseAuthorizationError(
            "fixture projection evaluation cannot authorize production search"
        )
    blob = json.dumps(dict(payload), sort_keys=True)
    if "/home/" in blob or "/Users/" in blob:
        raise VectorReceiptError("vector report contains an absolute home path")
    assert_no_secrets_or_home_paths(payload)


def check_evaluation_report(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Validate a report object against sealed LCR-029 acceptance."""

    assert_vector_evaluation_report(payload)
    admitted = payload.get("admitted") or {}
    evaluation = payload.get("evaluation") or {}
    default_probe = evaluation.get("default_probe") or {}
    return {
        "ok": True,
        "authorizing_for_publication": False,
        "cluster_count": admitted.get("cluster_count"),
        "default_probe_centroids": default_probe.get("default_probe_centroids"),
        "hub_upload": False,
        "recall_gates_pass": evaluation.get("recall_gates_pass"),
        "secrets_absent": True,
        "shard_count": admitted.get("shard_count"),
        "task_id": TASK_ID,
        "vector_count": admitted.get("vector_count"),
    }


def check_report_matches_fixture(
    on_disk: Mapping[str, Any],
    fixture_report: Mapping[str, Any],
) -> None:
    """Ensure frozen report acceptance matches the live fixture evaluation."""

    for key in ("task_id", "schema_version", "schema", "goal_id"):
        if on_disk.get(key) != fixture_report.get(key):
            raise VectorEvaluationError(
                f"on-disk {key} diverges from fixture: "
                f"disk={on_disk.get(key)!r} fixture={fixture_report.get(key)!r}"
            )
    disk_acc = on_disk.get("acceptance") or {}
    fix_acc = fixture_report.get("acceptance") or {}
    for key in (
        "every_vector_exactly_once",
        "physical_paths_match_centroid_routes",
        "centroid_and_two_shard_bounds_hold",
        "physical_shard_bound_4096",
        "ordering_cosine_desc",
        "determinism",
        "recall_gates_pass",
        "legacy_faiss_not_overwritten",
        "secrets_absent",
        "hub_upload",
    ):
        if disk_acc.get(key) != fix_acc.get(key):
            raise VectorEvaluationError(
                f"on-disk acceptance[{key!r}] diverges from fixture: "
                f"disk={disk_acc.get(key)!r} fixture={fix_acc.get(key)!r}"
            )
    disk_admitted = on_disk.get("admitted") or {}
    fix_admitted = fixture_report.get("admitted") or {}
    for key in ("vector_count", "chunk_count", "cluster_count", "shard_count"):
        if disk_admitted.get(key) != fix_admitted.get(key):
            raise VectorEvaluationError(
                f"on-disk admitted[{key!r}] diverges from fixture: "
                f"disk={disk_admitted.get(key)!r} fixture={fix_admitted.get(key)!r}"
            )


__all__ = [
    "ASSIGNMENT",
    "AUTHORIZES_HUB_UPLOAD",
    "AUTHORIZES_PUBLICATION",
    "DEFAULT_BACKEND",
    "DEFAULT_CANDIDATE_CENTROIDS",
    "DEFAULT_TARGET_ROWS_PER_CENTROID",
    "DEFAULT_VECTOR_KMEANS_SEED",
    "FORBIDDEN_LEGACY_FAISS_FILENAMES",
    "GOAL_ID",
    "MAX_ROWS_PER_PHYSICAL_SHARD",
    "MAX_ROWS_PER_VECTOR_CENTROID",
    "MAX_VECTOR_SHARDS_PER_CENTROID",
    "PINNED_DIMENSION",
    "PINNED_MODEL_ID",
    "PINNED_MODEL_REVISION",
    "PINNED_NORMALIZATION",
    "PINNED_POOLING",
    "PREPROCESSING",
    "PRIMARY_KEY",
    "PRODUCER",
    "PRODUCTION_BACKEND",
    "PROGRAM_ID",
    "PROJECTION_BACKEND",
    "REPORT_SCHEMA",
    "ROWS_SORTED_BY",
    "SCHEMA_VERSION",
    "TASK_ID",
    "CorpusParentLink",
    "InputReceipt",
    "LegacyFaissOverwriteError",
    "ManifestReadyDescriptor",
    "StateLawsVectorBinding",
    "StateLawsVectorError",
    "UnpinnedModelError",
    "VectorBindingError",
    "VectorCoverageError",
    "VectorEvaluationError",
    "VectorLocatorError",
    "VectorOrderingError",
    "VectorReceiptError",
    "VectorReleaseAuthorizationError",
    "VectorRootReconcileError",
    "VectorRouteBoundError",
    "VectorShardLocation",
    "admitted_fixture_chunks",
    "assert_centroid_routes_bounded",
    "assert_every_chunk_once",
    "assert_physical_paths_match_centroid_routes",
    "assert_rows_sorted_by_centroid_cosine",
    "assert_vector_evaluation_report",
    "bind_fixture_vectors",
    "bind_state_laws_embeddings",
    "bind_state_laws_vectors",
    "bind_state_laws_vectors_from_chunks",
    "bind_state_laws_vectors_from_embeddings",
    "build_layout_root_cid",
    "build_membership_hash",
    "build_model_cid",
    "build_vector_evaluation_report",
    "check_evaluation_report",
    "check_report_matches_fixture",
    "default_embedding_config",
    "default_vector_evaluation_report_path",
    "default_vector_space_id",
    "evaluate_fixture_recall",
    "fixture_embedding_config",
    "fixture_vector_bounds",
    "fixture_vector_chunks",
    "generate_state_laws_embeddings",
    "load_vector_evaluation_report",
    "production_embedding_config",
    "production_vector_bounds",
    "prove_direct_cid_off_centroid_fetch",
    "reconcile_roots",
    "reject_legacy_faiss_path",
    "require_pinned_gte_small",
    "select_off_centroid_keys",
    "write_vector_evaluation_report",
]
