"""Cluster, sort, and shard centroid-routed Open US Law vectors (OUL-029).

This module is the legal-domain adapter between:

* pinned embeddings from :mod:`open_us_law_embeddings` (OUL-028);
* domain-neutral deterministic balanced spherical k-means from
  :mod:`ipfs_datasets_py.retrieval.hf_graphrag.vectors` (OUL-026 / USCIR-018);
* hierarchical route pages from
  :mod:`ipfs_datasets_py.retrieval.hf_graphrag.hierarchical_routes` (OUL-026);
  and
* direct CID locators from
  :mod:`ipfs_datasets_py.retrieval.hf_graphrag.locators` (USCIR-011).

Design invariants
-----------------
* Deterministic balanced spherical k-means yields at most 8,192 rows and
  two physical shards per centroid.
* Every physical shard has at most 4,096 vectors.
* Rows inside a shard are sorted by descending cosine similarity to the
  shard centroid, then stable parent ``entry_cid``, then ``chunk_cid``.
* Cosine-sorted shard ``first_key`` / ``last_key`` values are **not**
  lexical CID ranges and must not be used to hydrate graph nodes.
* A dedicated ``entry_cid -> centroid/shard/row`` locator supports
  off-centroid graph-frontier hydration.
* Every embedded chunk appears in exactly one physical vector shard.
* Target occupancy is approximately 2,048 rows per centroid.
* Projection embeddings may exercise the software contract but cannot
  authorize a production candidate or release.
* No network I/O. Unit tests use compact sealed recipes only.
"""

from __future__ import annotations

import heapq
import json
import math
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final, Optional, Union

from ipfs_datasets_py.processors.legal_data.open_us_law_embeddings import (
    DEFAULT_BACKEND,
    DEFAULT_DEVICE,
    DEFAULT_PRECISION,
    DEFAULT_PROVIDER,
    EXACT_51_SEED_ROW_LOWER_BOUND,
    PINNED_DIMENSION,
    PINNED_MAX_TOKENS,
    PINNED_MODEL_ID,
    PINNED_MODEL_LICENSE,
    PINNED_MODEL_REVISION,
    PINNED_NORMALIZATION,
    PINNED_POOLING,
    PRODUCTION_BACKEND,
    PROJECTION_BACKEND,
    PROJECTION_FALLBACK_AUTHORIZES_RELEASE,
    EmbeddingGenerationResult,
    EmbeddingRecord,
    OpenUsLawEmbeddingConfig,
    default_embedding_config,
    default_vector_space_id,
    fixture_embedding_config,
    generate_open_us_law_embeddings,
    require_pinned_gte_small,
    write_json_atomic,
)
from ipfs_datasets_py.processors.legal_data.open_us_law_schema import (
    ADR_PATH as SCHEMA_ADR_PATH,
    InvalidDigestError,
    PositionalIdentityError,
    RELEASE_PROFILE,
    reject_positional_durable_identity,
    validate_digest,
    validate_entry_cid,
)
from ipfs_datasets_py.retrieval.hf_graphrag.hierarchical_routes import (
    HIERARCHICAL_ROUTE_SCHEMA_VERSION,
    HierarchicalRouteIndex,
    build_hierarchical_routes,
)
from ipfs_datasets_py.retrieval.hf_graphrag.locators import (
    KIND_VECTORS,
    LOCATOR_SCHEMA_VERSION,
    KeyLocatorIndex,
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
    canonical_json_bytes,
    content_sha256,
    normalize_relative_artifact_path,
    normalize_sha256,
)
from ipfs_datasets_py.retrieval.hf_graphrag.vectors import (
    ASSIGNMENT,
    DEFAULT_KMEANS_ITERATIONS,
    DEFAULT_MAX_CENTROIDS,
    DEFAULT_TARGET_ROWS_PER_CENTROID,
    DEFAULT_TRAINING_ROWS,
    DEFAULT_VECTOR_KMEANS_SEED,
    NORM_TOLERANCE,
    SCORE_TOLERANCE,
    VECTOR_DATA_DIR,
    VECTOR_INDEX_PATH,
    VECTOR_LAYOUT_SCHEMA_VERSION,
    VECTOR_ROUTING_SCHEMA_VERSION,
    VectorClusterGroup,
    VectorClusterLayout,
    VectorRecord,
    VectorShardRoute,
    VectorShardSpec,
    vector_bounds_policy,
    vector_shard_relative_path,
)

# ---------------------------------------------------------------------------
# Identity
# ---------------------------------------------------------------------------

SCHEMA_VERSION: Final = "open-us-law-vectors-v1"
RECEIPT_SCHEMA_VERSION: Final = "open-us-law-vector-receipt-v1"
TASK_ID: Final = "OUL-029"
GOAL_ID: Final = "OUL-G040"
PROGRAM_ID: Final = "open-us-law-reindex-v1"
PRODUCER: Final = "open_us_law_vectors.py"
ADR_PATH: Final = SCHEMA_ADR_PATH

PRIMARY_KEY: Final = "chunk_cid"
ENTRY_LOCATOR_KEY: Final = "entry_cid"
ROWS_SORTED_BY: Final = "centroid_cosine_desc_then_entry_cid"
EMPTY_CLUSTER_POLICY: Final = (
    "retain_previous_centroid_on_empty_training_assignment;"
    "drop_empty_groups_after_balanced_assignment"
)
VECTOR_ENTRY_LOCATOR_DIR: Final = "indexes/vector_entry_locator"
VECTOR_ENTRY_ROUTE_DIR: Final = "indexes/vector_entry_locator/routes"
VECTOR_KEY_FIELD: Final = "chunk_cid"

AUTHORIZES_PUBLICATION: Final = False
AUTHORIZES_RELEASE: Final = False
PROVES_SOFTWARE_CONTRACT_ONLY: Final = True
PROJECTION_FALLBACK_AUTHORIZES_VECTOR_RELEASE: Final = False

RECEIPT_RELATIVE_PATH: Final = "docs/reports/open_us_law_reindex/vector_receipt.json"
RECEIPT_SEALED_AT: Final = "2026-08-14T00:00:00Z"

DEFAULT_TEST_MAX_ROWS_PER_SHARD: Final = 2
DEFAULT_TEST_MAX_ROWS_PER_CENTROID: Final = 4
DEFAULT_TEST_TARGET_ROWS_PER_CENTROID: Final = 3
DEFAULT_TEST_ENTRY_LOCATOR_PAGE_SIZE: Final = 4

PathLike = Union[str, Path]
JsonMapping = Mapping[str, Any]


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class OpenUsLawVectorError(ValueError):
    """Base error for Open US Law vector clustering / binding failures."""

    code: str = "open_us_law_vector_error"

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        if code is not None:
            self.code = code

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "kind": "error", "message": str(self)}


class VectorBindingError(OpenUsLawVectorError):
    """Raised when embeddings cannot be bound to a vector layout."""

    code = "binding_invalid"


class VectorCoverageError(OpenUsLawVectorError):
    """Raised when chunk conservation or uniqueness fails."""

    code = "coverage_invalid"


class VectorRouteBoundError(OpenUsLawVectorError):
    """Raised when centroid or shard physical bounds are violated."""

    code = "route_bound_exceeded"


class VectorOrderingError(OpenUsLawVectorError):
    """Raised when shard rows are not cosine-then-entry-cid sorted."""

    code = "ordering_invalid"


class VectorRootReconcileError(OpenUsLawVectorError):
    """Raised when model/config/corpus/layout roots do not reconcile."""

    code = "root_reconcile_failed"


class VectorLocatorError(OpenUsLawVectorError):
    """Raised when entry-to-shard or off-centroid location fails."""

    code = "locator_failed"


class VectorReceiptError(OpenUsLawVectorError):
    """Raised when the sealed vector receipt is malformed."""

    code = "receipt_invalid"


class VectorReleaseAuthorizationError(OpenUsLawVectorError):
    """Raised when a vector binding or receipt would authorize release."""

    code = "vector_release_unauthorized"


# ---------------------------------------------------------------------------
# Helpers
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
    except (InvalidDigestError, PositionalIdentityError) as exc:
        raise VectorBindingError(str(exc), code="positional") from exc


def _prefixed_digest(hex_digest: str) -> str:
    return "sha256:" + normalize_sha256(hex_digest, name="digest")


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
    return _prefixed_digest(content_sha256(canonical_json_bytes(payload)))


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
                        "scores": [float(score) for score in shard.scores],
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
        "rows_sorted_by": ROWS_SORTED_BY,
        "schema_version": layout.schema_version,
        "seed": layout.seed,
        "total_rows": layout.total_rows,
    }
    return _prefixed_digest(content_sha256(canonical_json_bytes(structural)))


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
    return _prefixed_digest(content_sha256(canonical_json_bytes(payload)))


def layout_objective(layout: VectorClusterLayout) -> float:
    """Spherical k-means objective: sum of row-to-shard-centroid cosines."""

    return float(sum(float(score) for shard in layout.shards for score in shard.scores))


def _synthetic_shard_digest(relative_path: str, row_count: int) -> str:
    """Deterministic placeholder digest for in-memory (not-yet-written) shards."""

    return content_sha256(f"open-us-law-vector-shard:{relative_path}:rows={row_count}")


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

    def to_dict(self) -> dict[str, Any]:
        return {
            "chunk_cid": self.chunk_cid,
            "chunk_id": self.chunk_id,
            "document_index": self.document_index,
            "entry_cid": self.entry_cid,
            "legal_id": self.legal_id,
        }


@dataclass(frozen=True, slots=True)
class VectorShardLocation:
    """Exact location of one vector inside a centroid-routed data shard."""

    vector_key: str
    chunk_cid: str
    entry_cid: str
    relative_path: str
    cluster_id: int
    chunk_in_cluster: int
    global_shard_id: int
    row_offset: int
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
        object.__setattr__(self, "entry_cid", _durable_key(self.entry_cid, "entry_cid"))
        object.__setattr__(
            self,
            "relative_path",
            normalize_relative_artifact_path(self.relative_path),
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
        if self.sha256:
            object.__setattr__(self, "sha256", normalize_sha256(self.sha256, name="sha256"))
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
            normalize_relative_artifact_path(self.relative_path),
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
class OpenUsLawVectorBinding:
    """Complete Open US Law vector binding: centroid routes + entry locator."""

    layout: VectorClusterLayout
    routing_rows: tuple[dict[str, Any], ...]
    locations: Mapping[str, VectorShardLocation]
    entry_locations: Mapping[str, tuple[VectorShardLocation, ...]]
    parent_links: tuple[CorpusParentLink, ...]
    model_id: str
    model_revision: str
    vector_space_id: str
    config_cid: str
    model_cid: str
    vector_root_cid: str
    layout_seed: int
    membership_hash: str
    objective: float
    corpus_root_cid: Optional[str] = None
    embedding_config: Optional[OpenUsLawEmbeddingConfig] = None
    entry_locator_rows: tuple[LocatorRow, ...] = ()
    entry_route_index: Optional[HierarchicalRouteIndex] = None
    descriptors: tuple[ManifestReadyDescriptor, ...] = ()
    schema_version: str = SCHEMA_VERSION
    release_profile: str = RELEASE_PROFILE
    task_id: str = TASK_ID
    goal_id: str = GOAL_ID
    rows_sorted_by: str = ROWS_SORTED_BY
    empty_cluster_policy: str = EMPTY_CLUSTER_POLICY

    def __post_init__(self) -> None:
        if not isinstance(self.layout, VectorClusterLayout):
            raise VectorBindingError("layout must be a VectorClusterLayout")
        if not isinstance(self.locations, Mapping):
            raise VectorBindingError("locations must be a mapping")
        object.__setattr__(self, "locations", MappingProxyType(dict(self.locations)))
        if not isinstance(self.entry_locations, Mapping):
            raise VectorBindingError("entry_locations must be a mapping")
        object.__setattr__(
            self,
            "entry_locations",
            MappingProxyType(
                {key: tuple(value) for key, value in self.entry_locations.items()}
            ),
        )
        if len(self.locations) != self.layout.total_rows:
            raise VectorCoverageError(
                f"location map size {len(self.locations)} != layout "
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
        object.__setattr__(
            self,
            "membership_hash",
            validate_digest(self.membership_hash, name="membership_hash"),
        )
        object.__setattr__(self, "objective", float(self.objective))
        if self.corpus_root_cid is not None and str(self.corpus_root_cid).strip():
            object.__setattr__(
                self,
                "corpus_root_cid",
                validate_digest(self.corpus_root_cid, name="corpus_root_cid"),
            )
        else:
            object.__setattr__(self, "corpus_root_cid", None)
        object.__setattr__(self, "rows_sorted_by", ROWS_SORTED_BY)

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
        return tuple(sorted(self.entry_locations))

    def location_for(self, vector_key: str) -> VectorShardLocation:
        """Return the exact shard location for a durable vector (chunk) key."""

        key = _durable_key(vector_key, "vector_key")
        try:
            return self.locations[key]
        except KeyError as exc:
            raise MissingKeyError(
                f"vector key {key!r} is not covered by any vector shard"
            ) from exc

    def locate_vector(self, vector_key: str) -> LocatorHit:
        """Direct CID fetch for one embedded chunk, including off-centroid keys."""

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

    def locate_entry(self, entry_cid: str) -> tuple[VectorShardLocation, ...]:
        """Resolve one graph ``entry_cid`` to every containing vector shard row.

        This is the dedicated entry-to-shard locator used for off-centroid
        graph-frontier hydration. Cosine-sorted shard first/last keys are
        never consulted.
        """

        key = _durable_key(entry_cid, "entry_cid")
        locations = self.entry_locations.get(key)
        if not locations:
            raise MissingKeyError(
                f"entry_cid {key!r} is not covered by the vector entry locator"
            )
        return locations

    def locate_entries(
        self,
        entry_cids: Sequence[str],
        *,
        strict: bool = True,
    ) -> Mapping[str, tuple[VectorShardLocation, ...]]:
        resolved: dict[str, tuple[VectorShardLocation, ...]] = {}
        for position, raw in enumerate(entry_cids):
            try:
                locations = self.locate_entry(str(raw))
            except (MissingKeyError, VectorBindingError):
                if strict:
                    raise MissingKeyError(
                        f"entry_cids[{position}]={raw!r} is not covered"
                    ) from None
                continue
            resolved[locations[0].entry_cid] = locations
        return resolved

    def containing_vector_artifacts(
        self,
        vector_keys: Sequence[str],
        *,
        strict: bool = True,
    ) -> tuple[LocatorRow, ...]:
        """Minimal unique data-shard set required to hydrate *vector_keys*."""

        unique: dict[tuple[int, str], LocatorRow] = {}
        for position, raw in enumerate(vector_keys):
            try:
                hit = self.locate_vector(str(raw))
            except (MissingKeyError, VectorBindingError):
                if strict:
                    raise MissingKeyError(
                        f"vector_keys[{position}]={raw!r} is not covered"
                    ) from None
                continue
            path = hit.row.relative_path
            shard_rows = next(
                (
                    shard.row_count
                    for shard in self.layout.shards
                    if shard.relative_path == path
                ),
                hit.row.row_count,
            )
            unique[(hit.row.shard_id, path)] = LocatorRow(
                first_key=hit.row.first_key,
                last_key=hit.row.last_key,
                relative_path=path,
                sha256=hit.row.sha256,
                size_bytes=hit.row.size_bytes,
                row_count=shard_rows,
                shard_id=hit.row.shard_id,
                kind=KIND_VECTORS,
                schema_version=LOCATOR_SCHEMA_VERSION,
                content_cid=hit.row.content_cid,
                metadata=dict(hit.row.metadata),
            )
        return tuple(
            unique[key]
            for key in sorted(unique.keys(), key=lambda item: (item[0], item[1]))
        )

    def containing_entry_artifacts(
        self,
        entry_cids: Sequence[str],
        *,
        strict: bool = True,
    ) -> tuple[LocatorRow, ...]:
        """Minimal unique data-shard set required to hydrate *entry_cids*."""

        unique: dict[tuple[int, str], LocatorRow] = {}
        resolved = self.locate_entries(entry_cids, strict=strict)
        for locations in resolved.values():
            for location in locations:
                path = location.relative_path
                shard_rows = next(
                    (
                        shard.row_count
                        for shard in self.layout.shards
                        if shard.relative_path == path
                    ),
                    1,
                )
                unique[(location.global_shard_id, path)] = LocatorRow(
                    first_key=location.entry_cid,
                    last_key=location.entry_cid,
                    relative_path=path,
                    sha256=location.sha256
                    or _synthetic_shard_digest(path, shard_rows),
                    size_bytes=location.size_bytes,
                    row_count=shard_rows,
                    shard_id=location.global_shard_id,
                    kind=KIND_VECTORS,
                    schema_version=LOCATOR_SCHEMA_VERSION,
                    content_cid=location.content_cid,
                    metadata=location.locator_payload(),
                )
        return tuple(
            unique[key]
            for key in sorted(unique.keys(), key=lambda item: (item[0], item[1]))
        )

    def entry_locator_index(self) -> KeyLocatorIndex:
        """Bounded CID-range index over dedicated entry-locator pages."""

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
        """Bounded centroid routing for dense retrieval (no data-shard I/O)."""

        return route_open_us_law_shards(
            self.routing_rows,
            query_embedding,
            candidate_centroids=candidate_centroids,
            max_shards=max_shards,
        )

    def hydrate_off_centroid_frontier(
        self,
        entry_cids: Sequence[str],
        query_embedding: Sequence[float],
        *,
        candidate_centroids: int = 1,
        strict: bool = True,
    ) -> tuple[VectorShardLocation, ...]:
        """Hydrate graph-frontier entries whose shards are off the centroid set."""

        routes = self.route_centroids(
            query_embedding, candidate_centroids=candidate_centroids
        )
        routed_paths = {route.relative_path for route in routes}
        resolved = self.locate_entries(entry_cids, strict=strict)
        off: list[VectorShardLocation] = []
        for locations in resolved.values():
            for location in locations:
                if location.relative_path not in routed_paths:
                    off.append(location)
        return tuple(
            sorted(
                off,
                key=lambda item: (item.entry_cid, item.chunk_cid, item.row_offset),
            )
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
        return self.locate_entry(entry_cid)

    def receipt(self) -> dict[str, Any]:
        """Compact binding receipt for manifests / audit logs."""

        return {
            "assignment": ASSIGNMENT,
            "cluster_count": self.cluster_count,
            "config_cid": self.config_cid,
            "corpus_root_cid": self.corpus_root_cid,
            "dimension": self.layout.dimension,
            "empty_cluster_policy": self.empty_cluster_policy,
            "entry_locator_key": ENTRY_LOCATOR_KEY,
            "entry_locator_page_count": len(self.entry_locator_rows),
            "goal_id": self.goal_id,
            "hierarchical_entry_routes": self.entry_route_index is not None,
            "kmeans_iterations": self.layout.kmeans_iterations,
            "layout_seed": self.layout_seed,
            "max_rows_per_centroid": self.layout.max_rows_per_centroid,
            "max_rows_per_shard": self.layout.max_rows_per_shard,
            "max_shards_per_centroid": self.layout.max_shards_per_centroid,
            "membership_hash": self.membership_hash,
            "model_cid": self.model_cid,
            "model_id": self.model_id,
            "model_revision": self.model_revision,
            "objective": self.objective,
            "parent_link_count": len(self.parent_links),
            "primary_key": PRIMARY_KEY,
            "release_profile": self.release_profile,
            "rows_sorted_by": self.rows_sorted_by,
            "schema_version": self.schema_version,
            "shard_count": self.shard_count,
            "target_rows_per_centroid": self.layout.target_rows_per_centroid,
            "task_id": self.task_id,
            "vector_count": self.vector_count,
            "vector_root_cid": self.vector_root_cid,
            "vector_space_id": self.vector_space_id,
        }

    def to_dict(self, *, include_locations: bool = False) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "descriptors": [item.to_dict() for item in self.descriptors],
            "entry_cids": list(self.entry_cids),
            "entry_locator_rows": [row.to_dict() for row in self.entry_locator_rows],
            "layout": {
                **self.layout.manifest_config(),
                "rows_sorted_by": ROWS_SORTED_BY,
            },
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
# Input coercion
# ---------------------------------------------------------------------------


def _embedding_records_from_input(
    embeddings: (
        EmbeddingGenerationResult
        | Mapping[str, EmbeddingRecord | Mapping[str, Any] | Sequence[float]]
        | Sequence[EmbeddingRecord | Mapping[str, Any]]
    ),
) -> tuple[EmbeddingRecord, ...]:
    """Normalize heterogeneous embedding inputs into trusted records."""

    if isinstance(embeddings, EmbeddingGenerationResult):
        records = tuple(embeddings.embeddings[cid] for cid in sorted(embeddings.embeddings))
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
    pooling = str(value.get("pooling") or PINNED_POOLING)
    normalization = str(value.get("normalization") or PINNED_NORMALIZATION)
    vector_space_id = str(value.get("vector_space_id") or "").strip()
    if not vector_space_id:
        from ipfs_datasets_py.processors.legal_data.open_us_law_embeddings import (
            build_vector_space_id,
        )

        vector_space_id = build_vector_space_id(
            model_id=model_id,
            model_revision=model_revision,
            pooling=pooling,
            normalization=normalization,
            dimension=dimension,
        )
    config_cid = str(value.get("config_cid") or "").strip()
    if not config_cid:
        config_cid = _prefixed_digest(
            content_sha256(
                canonical_json_bytes(
                    {
                        "model_id": model_id,
                        "model_revision": model_revision,
                        "vector_space_id": vector_space_id,
                    }
                )
            )
        )
    input_hash = str(value.get("input_hash") or "").strip()
    if not input_hash:
        input_hash = content_sha256(f"input:{chunk_cid}")
    l2 = float(value.get("l2_norm") or 0.0)
    if l2 <= 0.0:
        l2 = math.sqrt(sum(float(x) * float(x) for x in embedding))
    entry_raw = value.get("entry_cid")
    entry_cid = (
        _durable_key(entry_raw, "entry_cid")
        if entry_raw is not None and str(entry_raw).strip()
        else None
    )
    return EmbeddingRecord(
        chunk_cid=chunk_cid,
        embedding=tuple(float(x) for x in embedding),
        dimension=dimension,
        input_hash=input_hash,
        model_id=model_id,
        model_revision=model_revision,
        vector_space_id=vector_space_id,
        pooling=pooling,
        normalization=normalization,
        l2_norm=l2,
        config_cid=config_cid,
        entry_cid=entry_cid,
        chunk_id=value.get("chunk_id"),
    )


def embeddings_to_vector_records(
    records: Sequence[EmbeddingRecord],
) -> tuple[VectorRecord, ...]:
    """Project trusted embedding records into domain-neutral vector rows.

    The physical layout key is ``chunk_cid`` (unique per embedded chunk).
    Parent ``entry_cid`` is preserved in metadata for the dedicated locator
    and for cosine-then-entry-cid shard ordering.
    """

    if not records:
        raise VectorBindingError("cannot bind an empty embedding set")
    seen: set[str] = set()
    rows: list[VectorRecord] = []
    for position, record in enumerate(records):
        if not isinstance(record, EmbeddingRecord):
            raise VectorBindingError(f"records[{position}] must be an EmbeddingRecord")
        key = record.chunk_cid
        if key in seen:
            raise VectorCoverageError(f"duplicate embedded chunk_cid: {key!r}")
        seen.add(key)
        parent = record.entry_cid or record.chunk_cid
        rows.append(
            VectorRecord(
                entry_cid=key,
                embedding=record.embedding,
                document_index=position,
                metadata={
                    "chunk_cid": record.chunk_cid,
                    "chunk_id": record.chunk_id,
                    "config_cid": record.config_cid,
                    "entry_cid": parent,
                    "input_hash": record.input_hash,
                    "model_id": record.model_id,
                    "model_revision": record.model_revision,
                    "vector_space_id": record.vector_space_id,
                },
            )
        )
    return tuple(rows)


def _parent_entry_cid(
    chunk_cid: str,
    records_by_chunk: Mapping[str, EmbeddingRecord],
) -> str:
    record = records_by_chunk.get(chunk_cid)
    if record is None:
        return chunk_cid
    if record.entry_cid is not None and str(record.entry_cid).strip():
        return str(record.entry_cid)
    return chunk_cid


def resort_layout_by_centroid_cosine_then_entry_cid(
    layout: VectorClusterLayout,
    *,
    records: Sequence[EmbeddingRecord],
) -> VectorClusterLayout:
    """Re-order every shard by cosine desc, then parent ``entry_cid``."""

    records_by_chunk = {record.chunk_cid: record for record in records}
    new_groups: list[VectorClusterGroup] = []
    for group in layout.clusters:
        new_shards: list[VectorShardSpec] = []
        for shard in group.shards:
            keyed: list[tuple[float, str, str, int]] = []
            for offset, chunk_cid in enumerate(shard.entry_cids):
                parent = _parent_entry_cid(chunk_cid, records_by_chunk)
                keyed.append((-float(shard.scores[offset]), parent, chunk_cid, offset))
            keyed.sort()
            order = [item[3] for item in keyed]
            new_scores = tuple(shard.scores[index] for index in order)
            new_shards.append(
                VectorShardSpec(
                    cluster_id=shard.cluster_id,
                    chunk_in_cluster=shard.chunk_in_cluster,
                    global_shard_id=shard.global_shard_id,
                    entry_cids=tuple(shard.entry_cids[index] for index in order),
                    document_indexes=tuple(
                        shard.document_indexes[index] for index in order
                    ),
                    embeddings=tuple(shard.embeddings[index] for index in order),
                    scores=new_scores,
                    routing_centroid=shard.routing_centroid,
                    shard_centroid=shard.shard_centroid,
                    min_score=float(min(new_scores)) if new_scores else 0.0,
                    max_score=float(max(new_scores)) if new_scores else 0.0,
                    relative_path=shard.relative_path,
                    dimension=shard.dimension,
                )
            )
        cluster_keys = tuple(cid for shard in new_shards for cid in shard.entry_cids)
        new_groups.append(
            replace(group, shards=tuple(new_shards), entry_cids=cluster_keys)
        )
    return replace(layout, clusters=tuple(new_groups))


# ---------------------------------------------------------------------------
# Locator page construction
# ---------------------------------------------------------------------------


def build_entry_locations(
    locations: Mapping[str, VectorShardLocation],
) -> dict[str, tuple[VectorShardLocation, ...]]:
    """Group physical vector locations by parent ``entry_cid``."""

    grouped: dict[str, list[VectorShardLocation]] = defaultdict(list)
    for location in locations.values():
        grouped[location.entry_cid].append(location)
    sealed: dict[str, tuple[VectorShardLocation, ...]] = {}
    for entry_cid in sorted(grouped):
        sealed[entry_cid] = tuple(
            sorted(
                grouped[entry_cid],
                key=lambda item: (
                    -item.centroid_cosine,
                    item.chunk_cid,
                    item.row_offset,
                ),
            )
        )
    return sealed


def build_entry_locator_rows(
    entry_locations: Mapping[str, Sequence[VectorShardLocation]],
    *,
    max_keys_per_page: int = MAX_ROWS_PER_PHYSICAL_SHARD,
    locator_dir: str = VECTOR_ENTRY_LOCATOR_DIR,
) -> tuple[LocatorRow, ...]:
    """Partition sorted ``entry_cid`` values into dedicated locator pages.

    Each page covers an inclusive ``[first_entry_cid, last_entry_cid]``
    range and stores the exact ``entry_cid -> centroid/shard/row`` map.
    Lookup never uses cosine-sorted data-shard first/last keys.
    """

    if not entry_locations:
        return ()
    max_keys = _require_positive_int(max_keys_per_page, "max_keys_per_page")
    if max_keys > MAX_ROWS_PER_PHYSICAL_SHARD:
        raise VectorRouteBoundError(
            f"max_keys_per_page={max_keys} exceeds {MAX_ROWS_PER_PHYSICAL_SHARD}"
        )
    directory = normalize_relative_artifact_path(locator_dir)
    ordered_keys = sorted(entry_locations)
    rows: list[LocatorRow] = []
    for page_index, offset in enumerate(range(0, len(ordered_keys), max_keys)):
        group = ordered_keys[offset : offset + max_keys]
        relative = f"{directory}/part-{page_index:06d}.parquet"
        page_payload = [
            {
                "entry_cid": key,
                "locations": [
                    location.locator_payload() for location in entry_locations[key]
                ],
            }
            for key in group
        ]
        digest = content_sha256(canonical_json_bytes({"rows": page_payload}))
        data_paths = sorted(
            {
                location.relative_path
                for key in group
                for location in entry_locations[key]
            }
        )
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
                    "data_paths": data_paths,
                    "entries": page_payload,
                    "kind": "vector_entry_locator_page",
                    "locator_key": ENTRY_LOCATOR_KEY,
                    "sort_order": ROWS_SORTED_BY,
                },
            )
        )
    if len(rows) > MAX_ROUTING_ROWS_PER_INDEX:
        raise VectorRouteBoundError(
            f"entry locator page count {len(rows)} exceeds {MAX_ROUTING_ROWS_PER_INDEX}"
        )
    return tuple(rows)


def build_entry_route_index(
    entry_locator_rows: Sequence[LocatorRow],
    *,
    route_dir: str = VECTOR_ENTRY_ROUTE_DIR,
) -> HierarchicalRouteIndex | None:
    """Integrity-bound hierarchical pages over the dedicated entry locator."""

    if not entry_locator_rows:
        return None
    descriptors = [
        {
            "first_key": row.first_key,
            "kind": KIND_VECTORS,
            "last_key": row.last_key,
            "relative_path": row.relative_path,
            "row_count": row.row_count,
            "sha256": row.sha256,
            "shard_id": row.shard_id,
            "size_bytes": row.size_bytes,
        }
        for row in entry_locator_rows
    ]
    return build_hierarchical_routes(
        descriptors,
        kind=KIND_VECTORS,
        route_dir=route_dir,
    )


# ---------------------------------------------------------------------------
# Location map from layout
# ---------------------------------------------------------------------------


def build_location_map(
    layout: VectorClusterLayout,
    *,
    records: Sequence[EmbeddingRecord],
    descriptors: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, VectorShardLocation]:
    """Build the exact ``chunk_cid -> shard location`` map from a layout."""

    parent_by_key = {rec.chunk_cid: rec for rec in records}
    descriptor_map = descriptors or {}
    locations: dict[str, VectorShardLocation] = {}
    for shard in layout.shards:
        extra = descriptor_map.get(shard.relative_path, {})
        sha256 = str(extra.get("sha256") or "") or _synthetic_shard_digest(
            shard.relative_path, shard.row_count
        )
        size_bytes = int(extra.get("size_bytes") or 0)
        content_cid = extra.get("content_cid") or extra.get("cid")
        for offset, vector_key in enumerate(shard.entry_cids):
            if vector_key in locations:
                raise VectorCoverageError(
                    f"duplicate vector key across shards: {vector_key!r}"
                )
            record = parent_by_key.get(vector_key)
            parent = (
                record.entry_cid
                if record is not None and record.entry_cid
                else vector_key
            )
            locations[vector_key] = VectorShardLocation(
                vector_key=vector_key,
                chunk_cid=vector_key,
                entry_cid=str(parent),
                relative_path=shard.relative_path,
                cluster_id=shard.cluster_id,
                chunk_in_cluster=shard.chunk_in_cluster,
                global_shard_id=shard.global_shard_id,
                row_offset=offset,
                document_index=(
                    shard.document_indexes[offset]
                    if offset < len(shard.document_indexes)
                    else offset
                ),
                sha256=sha256,
                size_bytes=size_bytes,
                content_cid=str(content_cid) if content_cid else None,
                dimension=shard.dimension,
                centroid_cosine=float(shard.scores[offset]) if offset < len(shard.scores) else 0.0,
            )
    if len(locations) != layout.total_rows:
        raise VectorCoverageError(
            f"location map has {len(locations)} keys; layout has {layout.total_rows} rows"
        )
    return locations


def build_parent_links(
    records: Sequence[EmbeddingRecord],
) -> tuple[CorpusParentLink, ...]:
    """Emit corpus parent links for chunks that declare an ``entry_cid``."""

    links: list[CorpusParentLink] = []
    for position, record in enumerate(records):
        parent = record.entry_cid or record.chunk_cid
        links.append(
            CorpusParentLink(
                chunk_cid=record.chunk_cid,
                entry_cid=parent,
                document_index=position,
                chunk_id=record.chunk_id,
            )
        )
    return tuple(sorted(links, key=lambda item: (item.entry_cid, item.chunk_cid)))


def build_manifest_descriptors(
    layout: VectorClusterLayout,
    *,
    routing_rows: Sequence[Mapping[str, Any]],
    entry_locator_rows: Sequence[LocatorRow],
    descriptors: Mapping[str, Mapping[str, Any]] | None = None,
    entry_route_index: HierarchicalRouteIndex | None = None,
) -> tuple[ManifestReadyDescriptor, ...]:
    """Assemble manifest-ready descriptors for data, routing, and locators."""

    descriptor_map = descriptors or {}
    out: list[ManifestReadyDescriptor] = []
    for shard in layout.shards:
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
                    "first_last_keys_are_not_lexical_ranges": True,
                    "global_shard_id": shard.global_shard_id,
                    "rows_sorted_by": ROWS_SORTED_BY,
                },
            )
        )
    routing_digest = content_sha256(
        canonical_json_bytes({"routing_rows": list(routing_rows)})
    )
    out.append(
        ManifestReadyDescriptor(
            relative_path=VECTOR_INDEX_PATH,
            family=ArtifactFamily.ROUTING_INDEX.value,
            row_count=len(routing_rows),
            sha256=routing_digest,
            schema_id=VECTOR_ROUTING_SCHEMA_VERSION,
            metadata={
                "first_last_keys_are_not_lexical_ranges": True,
                "kind": "centroid_routing_index",
            },
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
                metadata={
                    "kind": "vector_entry_locator_page",
                    "locator_key": ENTRY_LOCATOR_KEY,
                },
            )
        )
    if entry_route_index is not None:
        out.append(
            ManifestReadyDescriptor(
                relative_path=entry_route_index.root.relative_path,
                family=ArtifactFamily.ROUTING_INDEX.value,
                row_count=entry_route_index.root.leaf_count,
                sha256=entry_route_index.root.sha256,
                schema_id=HIERARCHICAL_ROUTE_SCHEMA_VERSION,
                first_key=entry_route_index.root.first_key,
                last_key=entry_route_index.root.last_key,
                metadata={
                    "height": entry_route_index.height
                    if hasattr(entry_route_index, "height")
                    else entry_route_index.root.level + 1,
                    "kind": "vector_entry_hierarchical_routes",
                    "legacy_single_page": bool(entry_route_index.is_legacy),
                },
            )
        )
    return tuple(out)


# ---------------------------------------------------------------------------
# Bound / sort validation
# ---------------------------------------------------------------------------


def assert_centroid_routes_bounded(layout: VectorClusterLayout) -> None:
    """Fail closed if any centroid/shard exceeds sealed physical bounds."""

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
        if group.row_count > MAX_ROWS_PER_VECTOR_CENTROID:
            raise VectorRouteBoundError(
                f"cluster {group.cluster_id} has {group.row_count} rows; "
                f"exceeds sealed {MAX_ROWS_PER_VECTOR_CENTROID}"
            )
        if group.shard_count > layout.max_shards_per_centroid:
            raise VectorRouteBoundError(
                f"cluster {group.cluster_id} has {group.shard_count} shards; "
                f"exceeds {layout.max_shards_per_centroid}"
            )
        if group.shard_count > MAX_VECTOR_SHARDS_PER_CENTROID:
            raise VectorRouteBoundError(
                f"cluster {group.cluster_id} has {group.shard_count} shards; "
                f"exceeds sealed {MAX_VECTOR_SHARDS_PER_CENTROID}"
            )
        for shard in group.shards:
            if shard.row_count > layout.max_rows_per_shard:
                raise VectorRouteBoundError(
                    f"shard {shard.relative_path} has {shard.row_count} rows; "
                    f"exceeds {layout.max_rows_per_shard}"
                )
            if shard.row_count > MAX_ROWS_PER_PHYSICAL_SHARD:
                raise VectorRouteBoundError(
                    f"shard {shard.relative_path} has {shard.row_count} rows; "
                    f"exceeds sealed {MAX_ROWS_PER_PHYSICAL_SHARD}"
                )


def assert_every_chunk_once(
    layout: VectorClusterLayout,
    *,
    expected_chunk_cids: Sequence[str],
) -> None:
    """Prove every embedded chunk appears exactly once in the layout."""

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


def assert_rows_sorted_by_centroid_cosine_then_entry_cid(
    binding: OpenUsLawVectorBinding,
) -> None:
    """Fail closed when a shard is not cosine-desc / entry_cid ordered."""

    for shard in binding.layout.shards:
        previous: tuple[float, str, str] | None = None
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
            current = (-score, location.entry_cid, chunk_cid)
            if previous is not None and current < previous:
                raise VectorOrderingError(
                    f"shard {shard.relative_path} is not sorted by "
                    f"{ROWS_SORTED_BY}"
                )
            previous = current


def shard_first_last_keys_are_lexical_ranges(
    routing_rows: Sequence[Mapping[str, Any]],
    locations: Mapping[str, VectorShardLocation],
) -> bool:
    """Return True only if shard first/last keys equal min/max entry CIDs.

    After cosine sorting this must be False whenever a shard holds more
    than one distinct parent ``entry_cid`` whose lexical order disagrees
    with the cosine order. Callers must use the dedicated entry locator.
    """

    by_path: dict[str, list[str]] = defaultdict(list)
    for location in locations.values():
        by_path[location.relative_path].append(location.entry_cid)
    for row in routing_rows:
        path = str(row.get("relative_path") or "")
        parents = by_path.get(path, [])
        if len(set(parents)) < 2:
            continue
        lexical_first = min(parents)
        lexical_last = max(parents)
        if row.get("first_key") == lexical_first and row.get("last_key") == lexical_last:
            continue
        return False
    return True


def reconcile_roots(
    binding: OpenUsLawVectorBinding,
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
    """Reconcile model/config/corpus/layout roots; fail closed on drift."""

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
            validate_digest(expected_corpus_root_cid, name="expected_corpus_root_cid"),
        )
    if expected_layout_seed is not None:
        _check("layout_seed", binding.layout_seed, int(expected_layout_seed))
    if expected_vector_root_cid is not None:
        _check(
            "vector_root_cid",
            binding.vector_root_cid,
            validate_digest(expected_vector_root_cid, name="expected_vector_root_cid"),
        )
    if expected_membership_hash is not None:
        _check(
            "membership_hash",
            binding.membership_hash,
            validate_digest(expected_membership_hash, name="expected_membership_hash"),
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
# Deterministic balanced spherical k-means (pure Python)
# ---------------------------------------------------------------------------
#
# The shared layout helper requires a working NumPy + BLAS stack. The
# sealed validation interpreter can import numpy's Python package while
# still failing to load ``libblas.so.3``. This implementation is the
# production algorithm for Open US Law: same bounds, seeded farthest-point
# init, iterative spherical refinement, capacity-constrained assignment,
# empty-cluster retention, and cosine-then-entry-cid shard order.


def _dot(left: Sequence[float], right: Sequence[float]) -> float:
    return float(sum(float(a) * float(b) for a, b in zip(left, right)))


def _euclid_norm(values: Sequence[float]) -> float:
    return math.sqrt(sum(float(value) * float(value) for value in values))


def _as_unit(values: Sequence[float]) -> tuple[float, ...]:
    norm = _euclid_norm(values)
    if not math.isfinite(norm) or norm <= 0.0:
        raise VectorBindingError("embedding must be finite and non-zero")
    return tuple(float(value) / norm for value in values)


def _mix64(value: int) -> int:
    x = value & 0xFFFFFFFFFFFFFFFF
    x = (x ^ (x >> 30)) * 0xBF58476D1CE4E5B9 & 0xFFFFFFFFFFFFFFFF
    x = (x ^ (x >> 27)) * 0x94D049BB133111EB & 0xFFFFFFFFFFFFFFFF
    return (x ^ (x >> 31)) & 0xFFFFFFFFFFFFFFFF


class _DeterministicRng:
    """Seeded 64-bit mixer used for farthest-point ties and training samples."""

    def __init__(self, seed: int) -> None:
        self._state = _mix64(int(seed) & 0x7FFFFFFF)

    def integers(self, high: int) -> int:
        if high < 1:
            raise VectorBindingError("rng upper bound must be positive")
        self._state = _mix64(self._state + 0x9E3779B97F4A7C15)
        return int(self._state % high)

    def sample_sorted(self, values: Sequence[int], count: int) -> list[int]:
        ordered = sorted(int(item) for item in values)
        if count >= len(ordered):
            return ordered
        pool = list(ordered)
        for offset in range(count):
            swap = offset + self.integers(len(pool) - offset)
            pool[offset], pool[swap] = pool[swap], pool[offset]
        return sorted(pool[:count])


def _balanced_capacities(row_count: int, group_count: int) -> list[int]:
    if group_count < 1 or group_count > row_count:
        raise VectorBindingError("balanced group count is malformed")
    base, remainder = divmod(row_count, group_count)
    return [base + (1 if group_id < remainder else 0) for group_id in range(group_count)]


def _balanced_position_groups(positions: Sequence[int], group_count: int) -> list[list[int]]:
    capacities = _balanced_capacities(len(positions), group_count)
    groups: list[list[int]] = []
    offset = 0
    for capacity in capacities:
        groups.append([int(value) for value in positions[offset : offset + capacity]])
        offset += capacity
    return groups


def _unit_centroid(
    matrix: Sequence[Sequence[float]],
    positions: Sequence[int],
) -> tuple[float, ...]:
    if not positions:
        raise VectorBindingError("cannot form a centroid from an empty group")
    dimension = len(matrix[positions[0]])
    totals = [0.0] * dimension
    for index in positions:
        row = matrix[index]
        for axis, value in enumerate(row):
            totals[axis] += float(value)
    scale = 1.0 / float(len(positions))
    mean = [value * scale for value in totals]
    norm = _euclid_norm(mean)
    if not math.isfinite(norm) or norm == 0.0:
        fallback = matrix[min(positions)]
        return _as_unit(fallback)
    return tuple(value / norm for value in mean)


def _learn_centroids(
    matrix: Sequence[Sequence[float]],
    positions: Sequence[int],
    cluster_count: int,
    *,
    iterations: int,
    seed: int,
    max_training_rows: int,
) -> list[tuple[float, ...]]:
    if cluster_count < 1 or cluster_count > len(positions):
        raise VectorBindingError("semantic centroid count is malformed")
    rng = _DeterministicRng(seed ^ (cluster_count * 0x9E3779B1))
    training = rng.sample_sorted(positions, min(len(positions), max_training_rows))
    first = rng.integers(len(training))
    selected: list[int] = [first]
    while len(selected) < cluster_count:
        nearest = []
        for local, source in enumerate(training):
            best = max(_dot(matrix[source], matrix[training[idx]]) for idx in selected)
            nearest.append(best)
        for idx in selected:
            nearest[idx] = float("inf")
        min_value = min(nearest)
        candidates = [
            local
            for local, value in enumerate(nearest)
            if math.isclose(value, min_value, abs_tol=1e-12, rel_tol=0.0)
            or value == min_value
        ]
        if len(candidates) == 1:
            selected.append(candidates[0])
        else:
            scored = [
                (
                    (int(seed) + 0xA5A5A5A5 + int(local) * 0x9E3779B97F4A7C15)
                    & 0xFFFFFFFFFFFFFFFF,
                    int(local),
                )
                for local in candidates
            ]
            scored.sort()
            selected.append(scored[0][1])
    centroids = [_as_unit(matrix[training[idx]]) for idx in selected]
    for _ in range(iterations):
        assignments = [
            max(
                range(cluster_count),
                key=lambda cluster_id: _dot(matrix[source], centroids[cluster_id]),
            )
            for source in training
        ]
        updated: list[tuple[float, ...]] = list(centroids)
        changed = False
        for cluster_id in range(cluster_count):
            members = [
                training[local]
                for local, assigned in enumerate(assignments)
                if assigned == cluster_id
            ]
            if not members:
                continue
            candidate = _unit_centroid(matrix, members)
            if candidate != updated[cluster_id]:
                updated[cluster_id] = candidate
                changed = True
        centroids = updated
        if not changed:
            break
    return centroids


def _capacity_constrained_assignments(
    scores: Sequence[Sequence[float]],
) -> list[int]:
    row_count = len(scores)
    cluster_count = len(scores[0]) if scores else 0
    if row_count < 1 or cluster_count < 1:
        raise VectorBindingError("centroid score matrix is malformed")
    capacities = _balanced_capacities(row_count, cluster_count)
    preferences = [
        sorted(range(cluster_count), key=lambda cluster_id: (-float(row[cluster_id]), cluster_id))
        for row in scores
    ]
    next_preference = [0] * row_count
    assignments = [-1] * row_count
    accepted: list[list[tuple[float, int, int]]] = [[] for _ in range(cluster_count)]
    pending = list(range(row_count))
    while pending:
        row_id = pending.pop(0)
        rank = next_preference[row_id]
        if rank >= cluster_count:
            raise VectorCoverageError("capacity-constrained assignment did not converge")
        cluster_id = preferences[row_id][rank]
        next_preference[row_id] = rank + 1
        proposal = (float(scores[row_id][cluster_id]), -row_id, row_id)
        retained = accepted[cluster_id]
        capacity = capacities[cluster_id]
        if len(retained) < capacity:
            heapq.heappush(retained, proposal)
            assignments[row_id] = cluster_id
        elif proposal[:2] > retained[0][:2]:
            displaced = heapq.heapreplace(retained, proposal)
            assignments[int(displaced[2])] = -1
            pending.append(int(displaced[2]))
            assignments[row_id] = cluster_id
        else:
            pending.append(row_id)
    if any(value < 0 for value in assignments):
        raise VectorCoverageError("balanced centroid assignment coverage differs")
    return assignments


def _spherical_kmeans_groups(
    matrix: Sequence[Sequence[float]],
    positions: Sequence[int],
    cluster_count: int,
    *,
    seed: int,
    iterations: int,
    max_training_rows: int,
) -> list[list[int]]:
    position_list = [int(value) for value in positions]
    row_count = len(position_list)
    if row_count == 0:
        return []
    cluster_count = min(int(cluster_count), row_count)
    if cluster_count < 1:
        raise VectorBindingError("spherical vector cluster count must be positive")
    if cluster_count == 1:
        return [position_list]
    centroids = _learn_centroids(
        matrix,
        position_list,
        cluster_count,
        iterations=iterations,
        seed=seed,
        max_training_rows=max_training_rows,
    )
    scores = [
        [_dot(matrix[index], centroid) for centroid in centroids]
        for index in position_list
    ]
    assignments = _capacity_constrained_assignments(scores)
    groups = [[] for _ in range(cluster_count)]
    for local, cluster_id in enumerate(assignments):
        groups[cluster_id].append(position_list[local])
    return [group for group in groups if group]


def _recursive_bounded_groups(
    matrix: Sequence[Sequence[float]],
    positions: Sequence[int],
    *,
    max_rows_per_centroid: int,
    target_rows_per_centroid: int,
    seed: int,
    iterations: int,
    max_training_rows: int,
    max_centroids: int,
    depth: int = 0,
) -> list[list[int]]:
    position_list = [int(value) for value in positions]
    row_count = len(position_list)
    if row_count == 0:
        return []
    if row_count <= max_rows_per_centroid:
        if row_count <= target_rows_per_centroid or row_count < 2:
            return [position_list]
        desired = math.ceil(row_count / target_rows_per_centroid)
        desired = min(desired, row_count, max_centroids)
        if desired <= 1:
            return [position_list]
        children = _spherical_kmeans_groups(
            matrix,
            position_list,
            desired,
            seed=seed + depth * 1_000_003,
            iterations=iterations,
            max_training_rows=max_training_rows,
        )
        if len(children) < 2:
            return [position_list]
        output: list[list[int]] = []
        for child_index, child in enumerate(children):
            output.extend(
                _recursive_bounded_groups(
                    matrix,
                    child,
                    max_rows_per_centroid=max_rows_per_centroid,
                    target_rows_per_centroid=target_rows_per_centroid,
                    seed=seed + 10_000 + child_index * 257 + depth,
                    iterations=iterations,
                    max_training_rows=max_training_rows,
                    max_centroids=max_centroids,
                    depth=depth + 1,
                )
            )
        return output

    required = math.ceil(row_count / max_rows_per_centroid)
    desired = math.ceil(row_count / target_rows_per_centroid)
    cluster_count = max(2, required, desired)
    cluster_count = min(cluster_count, row_count, max_centroids)
    children = _spherical_kmeans_groups(
        matrix,
        position_list,
        cluster_count,
        seed=seed + depth * 1_000_003,
        iterations=iterations,
        max_training_rows=max_training_rows,
    )
    if len(children) < 2 or max(map(len, children)) == row_count:
        ordered = sorted(position_list)
        children = [
            ordered[start : start + max_rows_per_centroid]
            for start in range(0, row_count, max_rows_per_centroid)
        ]
    output = []
    for child_index, child in enumerate(children):
        output.extend(
            _recursive_bounded_groups(
                matrix,
                child,
                max_rows_per_centroid=max_rows_per_centroid,
                target_rows_per_centroid=target_rows_per_centroid,
                seed=seed + 10_000 + child_index * 257 + depth,
                iterations=iterations,
                max_training_rows=max_training_rows,
                max_centroids=max_centroids,
                depth=depth + 1,
            )
        )
    return output


def _physical_shards(
    matrix: Sequence[Sequence[float]],
    positions: Sequence[int],
    *,
    max_rows_per_shard: int,
    max_shards_per_centroid: int,
    seed: int,
    iterations: int,
    max_training_rows: int,
) -> list[list[int]]:
    position_list = [int(value) for value in positions]
    row_count = len(position_list)
    if row_count == 0:
        return []
    shard_count = math.ceil(row_count / max_rows_per_shard)
    if shard_count <= 1:
        return [position_list]
    if shard_count > max_shards_per_centroid:
        raise VectorCoverageError(
            f"centroid requires {shard_count} physical shards; "
            f"maximum is {max_shards_per_centroid}"
        )
    if row_count < shard_count:
        return _balanced_position_groups(position_list, shard_count)
    children = _spherical_kmeans_groups(
        matrix,
        position_list,
        shard_count,
        seed=seed,
        iterations=iterations,
        max_training_rows=max_training_rows,
    )
    if len(children) != shard_count:
        return _balanced_position_groups(position_list, shard_count)
    children = sorted(children, key=lambda group: (min(group), len(group), group[0]))
    return children


def build_open_us_law_centroid_layout(
    records: Sequence[EmbeddingRecord],
    *,
    seed: int = DEFAULT_VECTOR_KMEANS_SEED,
    max_rows_per_shard: int = MAX_ROWS_PER_PHYSICAL_SHARD,
    max_shards_per_centroid: int = MAX_VECTOR_SHARDS_PER_CENTROID,
    max_rows_per_centroid: int | None = None,
    target_rows_per_centroid: int = DEFAULT_TARGET_ROWS_PER_CENTROID,
    max_centroids: int = DEFAULT_MAX_CENTROIDS,
    kmeans_iterations: int = DEFAULT_KMEANS_ITERATIONS,
    max_training_rows: int = DEFAULT_TRAINING_ROWS,
    data_dir: str = VECTOR_DATA_DIR,
) -> VectorClusterLayout:
    """Cluster embeddings with deterministic balanced spherical k-means."""

    bounds = _coerce_layout_bounds(
        seed=seed,
        max_rows_per_shard=max_rows_per_shard,
        max_shards_per_centroid=max_shards_per_centroid,
        max_rows_per_centroid=max_rows_per_centroid,
        target_rows_per_centroid=target_rows_per_centroid,
        kmeans_iterations=kmeans_iterations,
    )
    if not records:
        raise VectorBindingError("cannot cluster an empty embedding set")
    ordered = tuple(sorted(records, key=lambda item: (item.chunk_cid, item.entry_cid or "")))
    matrix = [_as_unit(record.embedding) for record in ordered]
    dimension = len(matrix[0])
    if any(len(row) != dimension for row in matrix):
        raise VectorBindingError("embedding dimensions are not uniform")
    chunk_cids = tuple(record.chunk_cid for record in ordered)
    parent_cids = tuple(record.entry_cid or record.chunk_cid for record in ordered)
    document_indexes = tuple(index for index, _ in enumerate(ordered))

    groups = _recursive_bounded_groups(
        matrix,
        list(range(len(ordered))),
        max_rows_per_centroid=bounds["max_rows_per_centroid"],
        target_rows_per_centroid=bounds["target_rows_per_centroid"],
        seed=bounds["seed"],
        iterations=bounds["kmeans_iterations"],
        max_training_rows=max_training_rows,
        max_centroids=max_centroids,
    )
    if not groups:
        raise VectorCoverageError("vector centroid coverage is empty")
    groups = sorted(
        groups,
        key=lambda group: (
            min(chunk_cids[index] for index in group),
            len(group),
            min(group),
        ),
    )

    cluster_groups: list[VectorClusterGroup] = []
    global_shard_id = 0
    for cluster_id, group_positions in enumerate(groups):
        if len(group_positions) > bounds["max_rows_per_centroid"]:
            raise VectorCoverageError(
                f"cluster {cluster_id} has {len(group_positions)} rows; "
                f"exceeds {bounds['max_rows_per_centroid']}"
            )
        routing_centroid = _unit_centroid(matrix, group_positions)
        physical = _physical_shards(
            matrix,
            group_positions,
            max_rows_per_shard=bounds["max_rows_per_shard"],
            max_shards_per_centroid=bounds["max_shards_per_centroid"],
            seed=bounds["seed"] + 1_000_000 + cluster_id * 97,
            iterations=bounds["kmeans_iterations"],
            max_training_rows=max_training_rows,
        )
        if not 1 <= len(physical) <= bounds["max_shards_per_centroid"]:
            raise VectorCoverageError(
                f"cluster {cluster_id} produced {len(physical)} shards; "
                f"expected 1..{bounds['max_shards_per_centroid']}"
            )
        shard_specs: list[VectorShardSpec] = []
        for chunk_in_cluster, selected in enumerate(physical):
            if len(selected) > bounds["max_rows_per_shard"]:
                raise VectorCoverageError(
                    f"shard cluster={cluster_id} chunk={chunk_in_cluster} "
                    f"has {len(selected)} rows; exceeds {bounds['max_rows_per_shard']}"
                )
            shard_centroid = _unit_centroid(matrix, selected)
            keyed = []
            for index in selected:
                score = _dot(matrix[index], shard_centroid)
                keyed.append((-score, parent_cids[index], chunk_cids[index], index))
            keyed.sort()
            ordered_positions = [item[3] for item in keyed]
            ordered_scores = tuple(-item[0] for item in keyed)
            shard_specs.append(
                VectorShardSpec(
                    cluster_id=cluster_id,
                    chunk_in_cluster=chunk_in_cluster,
                    global_shard_id=global_shard_id,
                    entry_cids=tuple(chunk_cids[index] for index in ordered_positions),
                    document_indexes=tuple(
                        document_indexes[index] for index in ordered_positions
                    ),
                    embeddings=tuple(matrix[index] for index in ordered_positions),
                    scores=ordered_scores,
                    routing_centroid=routing_centroid,
                    shard_centroid=shard_centroid,
                    min_score=float(min(ordered_scores)) if ordered_scores else 0.0,
                    max_score=float(max(ordered_scores)) if ordered_scores else 0.0,
                    relative_path=vector_shard_relative_path(
                        cluster_id, chunk_in_cluster, data_dir=data_dir
                    ),
                    dimension=dimension,
                )
            )
            global_shard_id += 1
        cluster_keys = tuple(cid for shard in shard_specs for cid in shard.entry_cids)
        cluster_groups.append(
            VectorClusterGroup(
                cluster_id=cluster_id,
                entry_cids=cluster_keys,
                routing_centroid=routing_centroid,
                shards=tuple(shard_specs),
            )
        )

    layout = VectorClusterLayout(
        clusters=tuple(cluster_groups),
        dimension=dimension,
        total_rows=len(ordered),
        seed=bounds["seed"],
        max_rows_per_shard=bounds["max_rows_per_shard"],
        max_rows_per_centroid=bounds["max_rows_per_centroid"],
        max_shards_per_centroid=bounds["max_shards_per_centroid"],
        target_rows_per_centroid=bounds["target_rows_per_centroid"],
        kmeans_iterations=bounds["kmeans_iterations"],
    )
    return layout


# ---------------------------------------------------------------------------
# Main bind API
# ---------------------------------------------------------------------------


def _coerce_layout_bounds(
    *,
    seed: int,
    max_rows_per_shard: int,
    max_shards_per_centroid: int,
    max_rows_per_centroid: int | None,
    target_rows_per_centroid: int,
    kmeans_iterations: int,
) -> dict[str, int]:
    seed = _require_non_negative_int(seed, "seed")
    max_rows_per_shard = _require_positive_int(max_rows_per_shard, "max_rows_per_shard")
    max_shards_per_centroid = _require_positive_int(
        max_shards_per_centroid, "max_shards_per_centroid"
    )
    target_rows_per_centroid = _require_positive_int(
        target_rows_per_centroid, "target_rows_per_centroid"
    )
    kmeans_iterations = _require_positive_int(kmeans_iterations, "kmeans_iterations")
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
    if max_rows_per_centroid is None:
        max_rows_per_centroid = max_rows_per_shard * max_shards_per_centroid
    max_rows_per_centroid = _require_positive_int(
        max_rows_per_centroid, "max_rows_per_centroid"
    )
    if max_rows_per_centroid > MAX_ROWS_PER_VECTOR_CENTROID:
        raise VectorRouteBoundError(
            f"max_rows_per_centroid={max_rows_per_centroid} exceeds "
            f"{MAX_ROWS_PER_VECTOR_CENTROID}"
        )
    return {
        "kmeans_iterations": kmeans_iterations,
        "max_rows_per_centroid": max_rows_per_centroid,
        "max_rows_per_shard": max_rows_per_shard,
        "max_shards_per_centroid": max_shards_per_centroid,
        "seed": seed,
        "target_rows_per_centroid": target_rows_per_centroid,
    }


def bind_open_us_law_vectors(
    embeddings: (
        EmbeddingGenerationResult
        | Mapping[str, EmbeddingRecord | Mapping[str, Any] | Sequence[float]]
        | Sequence[EmbeddingRecord | Mapping[str, Any]]
    ),
    *,
    corpus_root_cid: str | None = None,
    config: OpenUsLawEmbeddingConfig | None = None,
    seed: int = DEFAULT_VECTOR_KMEANS_SEED,
    max_rows_per_shard: int = MAX_ROWS_PER_PHYSICAL_SHARD,
    max_shards_per_centroid: int = MAX_VECTOR_SHARDS_PER_CENTROID,
    max_rows_per_centroid: int | None = None,
    target_rows_per_centroid: int = DEFAULT_TARGET_ROWS_PER_CENTROID,
    kmeans_iterations: int = DEFAULT_KMEANS_ITERATIONS,
    data_dir: str = VECTOR_DATA_DIR,
    entry_locator_page_size: int = MAX_ROWS_PER_PHYSICAL_SHARD,
    shard_descriptors: Mapping[str, Mapping[str, Any]] | None = None,
) -> OpenUsLawVectorBinding:
    """Bind trusted Open US Law embeddings to centroid routes and an entry locator."""

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
    if config is not None:
        if (
            config.model_id != first.model_id
            or config.model_revision != first.model_revision
            or config.vector_space_id != first.vector_space_id
            or config.config_cid != first.config_cid
        ):
            raise VectorRootReconcileError(
                "supplied embedding config does not match embedding pin"
            )
        bound_config = config
    else:
        bound_config = None

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
    bounds = _coerce_layout_bounds(
        seed=seed,
        max_rows_per_shard=max_rows_per_shard,
        max_shards_per_centroid=max_shards_per_centroid,
        max_rows_per_centroid=max_rows_per_centroid,
        target_rows_per_centroid=target_rows_per_centroid,
        kmeans_iterations=kmeans_iterations,
    )
    layout = build_open_us_law_centroid_layout(
        records,
        seed=bounds["seed"],
        max_rows_per_shard=bounds["max_rows_per_shard"],
        max_shards_per_centroid=bounds["max_shards_per_centroid"],
        max_rows_per_centroid=bounds["max_rows_per_centroid"],
        target_rows_per_centroid=bounds["target_rows_per_centroid"],
        kmeans_iterations=bounds["kmeans_iterations"],
        data_dir=data_dir,
    )
    layout = resort_layout_by_centroid_cosine_then_entry_cid(layout, records=records)
    assert_every_chunk_once(layout, expected_chunk_cids=chunk_cids)
    assert_centroid_routes_bounded(layout)

    locations = build_location_map(
        layout, records=records, descriptors=shard_descriptors
    )
    entry_locations = build_entry_locations(locations)
    parent_links = build_parent_links(records)
    routing_rows = layout.routing_rows(descriptors=shard_descriptors)
    for row in routing_rows:
        row["first_last_keys_are_not_lexical_ranges"] = True
        row["rows_sorted_by"] = ROWS_SORTED_BY
    entry_locator_rows = build_entry_locator_rows(
        entry_locations, max_keys_per_page=entry_locator_page_size
    )
    entry_route_index = build_entry_route_index(entry_locator_rows)
    descriptors = build_manifest_descriptors(
        layout,
        routing_rows=routing_rows,
        entry_locator_rows=entry_locator_rows,
        descriptors=shard_descriptors,
        entry_route_index=entry_route_index,
    )
    vector_root_cid = build_layout_root_cid(layout)
    membership = build_membership_hash(layout)
    corpus_root: Optional[str] = None
    if corpus_root_cid is not None and str(corpus_root_cid).strip():
        corpus_root = validate_digest(corpus_root_cid, name="corpus_root_cid")

    binding = OpenUsLawVectorBinding(
        layout=layout,
        routing_rows=tuple(dict(row) for row in routing_rows),
        locations=locations,
        entry_locations=entry_locations,
        parent_links=parent_links,
        model_id=model_id,
        model_revision=model_revision,
        vector_space_id=vector_space_id,
        config_cid=config_cid,
        model_cid=model_cid,
        vector_root_cid=vector_root_cid,
        layout_seed=layout.seed,
        membership_hash=membership,
        objective=layout_objective(layout),
        corpus_root_cid=corpus_root,
        embedding_config=bound_config,
        entry_locator_rows=entry_locator_rows,
        entry_route_index=entry_route_index,
        descriptors=descriptors,
    )
    assert_rows_sorted_by_centroid_cosine_then_entry_cid(binding)
    reconcile_roots(
        binding,
        expected_model_id=model_id,
        expected_model_revision=model_revision,
        expected_config_cid=config_cid,
        expected_vector_space_id=vector_space_id,
        expected_corpus_root_cid=corpus_root,
        expected_layout_seed=bounds["seed"],
        expected_vector_root_cid=vector_root_cid,
        expected_membership_hash=membership,
    )
    return binding


def bind_open_us_law_vectors_from_chunks(
    chunks: Sequence[Mapping[str, Any]],
    *,
    corpus_root_cid: str | None = None,
    config: OpenUsLawEmbeddingConfig | None = None,
    seed: int = DEFAULT_VECTOR_KMEANS_SEED,
    max_rows_per_shard: int = MAX_ROWS_PER_PHYSICAL_SHARD,
    max_shards_per_centroid: int = MAX_VECTOR_SHARDS_PER_CENTROID,
    max_rows_per_centroid: int | None = None,
    target_rows_per_centroid: int = DEFAULT_TARGET_ROWS_PER_CENTROID,
    kmeans_iterations: int = DEFAULT_KMEANS_ITERATIONS,
    entry_locator_page_size: int = MAX_ROWS_PER_PHYSICAL_SHARD,
    embedder: Any | None = None,
    device_probe: Any | None = None,
) -> OpenUsLawVectorBinding:
    """Embed admitted chunks, then bind centroid routes and the entry locator.

    Production callers must pass a sentence-transformers config. Unit
    fixtures may pass :func:`fixture_embedding_config`; that backend
    cannot authorize release.
    """

    pin = config or fixture_embedding_config()
    result = generate_open_us_law_embeddings(
        chunks,
        config=pin,
        embedder=embedder,
        device_probe=device_probe,
    )
    return bind_open_us_law_vectors(
        result,
        corpus_root_cid=corpus_root_cid,
        config=pin,
        seed=seed,
        max_rows_per_shard=max_rows_per_shard,
        max_shards_per_centroid=max_shards_per_centroid,
        max_rows_per_centroid=max_rows_per_centroid,
        target_rows_per_centroid=target_rows_per_centroid,
        kmeans_iterations=kmeans_iterations,
        entry_locator_page_size=entry_locator_page_size,
    )


# ---------------------------------------------------------------------------
# Off-centroid / frontier helpers
# ---------------------------------------------------------------------------


def route_open_us_law_shards(
    routing_rows: Sequence[Mapping[str, Any]],
    query_embedding: Sequence[float],
    *,
    candidate_centroids: int = DEFAULT_CANDIDATE_CENTROIDS,
    max_shards: int | None = None,
) -> tuple[VectorShardRoute, ...]:
    """Rank routing centroids without NumPy and return selected shard routes."""

    candidate_centroids = _require_positive_int(candidate_centroids, "candidate_centroids")
    if max_shards is None:
        max_shards = candidate_centroids * MAX_VECTOR_SHARDS_PER_CENTROID
    max_shards = _require_positive_int(max_shards, "max_shards")
    if not routing_rows:
        raise VectorLocatorError("vector routing meta-index is empty")

    groups: dict[int, list[Mapping[str, Any]]] = {}
    dimensions: set[int] = set()
    for row in routing_rows:
        if not isinstance(row, Mapping):
            raise VectorLocatorError("routing row must be a mapping")
        cluster_id = int(row["cluster_id"])
        groups.setdefault(cluster_id, []).append(row)
        dimensions.add(int(row["dimension"]))
    if len(dimensions) != 1:
        raise VectorLocatorError("routing metadata mixes embedding dimensions")
    dimension = next(iter(dimensions))
    if dimension < 1:
        raise VectorLocatorError("routing dimension must be positive")
    if len(query_embedding) != dimension:
        raise VectorLocatorError("query embedding dimension differs")
    if any(not math.isfinite(float(value)) for value in query_embedding):
        raise VectorLocatorError("query embedding contains non-finite values")
    query = _as_unit(query_embedding)

    ranked: list[tuple[float, int, list[Mapping[str, Any]]]] = []
    for cluster_id, group in groups.items():
        ordered = sorted(group, key=lambda row: int(row["chunk_in_cluster"]))
        if [int(row["chunk_in_cluster"]) for row in ordered] != list(range(len(ordered))):
            raise VectorLocatorError(f"cluster {cluster_id} chunk numbering differs")
        if any(int(row["centroid_shard_count"]) != len(ordered) for row in ordered):
            raise VectorLocatorError(f"cluster {cluster_id} shard count differs")
        centroid = tuple(float(value) for value in ordered[0]["centroid"])
        if len(centroid) != dimension:
            raise VectorLocatorError(f"cluster {cluster_id} centroid dimension differs")
        for row in ordered[1:]:
            other = tuple(float(value) for value in row["centroid"])
            if any(
                not math.isclose(left, right, abs_tol=NORM_TOLERANCE, rel_tol=0.0)
                for left, right in zip(other, centroid)
            ):
                raise VectorLocatorError(
                    f"cluster {cluster_id} routing centroid differs across shards"
                )
        centroid_norm = _euclid_norm(centroid)
        if not math.isclose(centroid_norm, 1.0, abs_tol=NORM_TOLERANCE, rel_tol=0.0):
            raise VectorLocatorError(
                f"cluster {cluster_id} routing centroid is not normalized"
            )
        ranked.append((_dot(query, centroid), cluster_id, ordered))

    if not ranked:
        raise VectorLocatorError("no searchable semantic centroids")
    ranked.sort(key=lambda item: (-item[0], item[1]))

    routes: list[VectorShardRoute] = []
    for score, cluster_id, group in ranked[:candidate_centroids]:
        for row in group:
            if len(routes) >= max_shards:
                return tuple(routes)
            routes.append(
                VectorShardRoute(
                    cluster_id=cluster_id,
                    chunk_in_cluster=int(row["chunk_in_cluster"]),
                    score=score,
                    relative_path=str(row["relative_path"]),
                    row_count=int(row["row_count"]),
                    shard_id=int(row["shard_id"]),
                    sha256=str(row.get("sha256") or ""),
                    size_bytes=int(row.get("size_bytes") or 0),
                    content_cid=(
                        str(row["content_cid"])
                        if row.get("content_cid")
                        else (str(row["cid"]) if row.get("cid") else None)
                    ),
                )
            )
    return tuple(routes)


def select_off_centroid_keys(
    binding: OpenUsLawVectorBinding,
    query_embedding: Sequence[float],
    *,
    candidate_centroids: int = 1,
) -> tuple[str, ...]:
    """Return chunk keys whose data shards are outside the centroid route set."""

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


def select_off_centroid_entry_cids(
    binding: OpenUsLawVectorBinding,
    query_embedding: Sequence[float],
    *,
    candidate_centroids: int = 1,
) -> tuple[str, ...]:
    """Return parent ``entry_cid`` values that require off-centroid hydration."""

    routes = binding.route_centroids(
        query_embedding, candidate_centroids=candidate_centroids
    )
    routed_paths = {route.relative_path for route in routes}
    off: list[str] = []
    for entry_cid, locations in sorted(binding.entry_locations.items()):
        if any(location.relative_path not in routed_paths for location in locations):
            off.append(entry_cid)
    return tuple(off)


def prove_direct_cid_off_centroid_fetch(
    binding: OpenUsLawVectorBinding,
    query_embedding: Sequence[float],
    *,
    candidate_centroids: int = 1,
) -> dict[str, Any]:
    """Prove direct CID locate works for at least one off-centroid key."""

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


def prove_entry_locator_off_centroid_hydration(
    binding: OpenUsLawVectorBinding,
    query_embedding: Sequence[float],
    *,
    candidate_centroids: int = 1,
) -> dict[str, Any]:
    """Prove the dedicated entry locator hydrates off-centroid graph nodes."""

    off_entries = select_off_centroid_entry_cids(
        binding, query_embedding, candidate_centroids=candidate_centroids
    )
    if not off_entries:
        raise VectorLocatorError(
            "no off-centroid entry_cid values for the given probe budget"
        )
    routes = binding.route_centroids(
        query_embedding, candidate_centroids=candidate_centroids
    )
    routed_paths = {route.relative_path for route in routes}
    index = binding.entry_locator_index()
    samples: list[dict[str, Any]] = []
    for entry_cid in off_entries:
        page = index.locate(entry_cid)
        if not page.row.contains(entry_cid):
            raise VectorLocatorError(
                f"entry locator page does not cover {entry_cid!r}"
            )
        locations = binding.locate_entry(entry_cid)
        if not locations:
            raise VectorLocatorError(f"entry locator returned no rows for {entry_cid!r}")
        off_rows = [
            location
            for location in locations
            if location.relative_path not in routed_paths
        ]
        if not off_rows:
            raise VectorLocatorError(
                f"entry {entry_cid!r} unexpectedly has no off-centroid shards"
            )
        hydrated = binding.hydrate_off_centroid_frontier(
            [entry_cid],
            query_embedding,
            candidate_centroids=candidate_centroids,
        )
        if not hydrated:
            raise VectorLocatorError(
                f"frontier hydration missed off-centroid entry {entry_cid!r}"
            )
        samples.append(
            {
                "entry_cid": entry_cid,
                "locator_page": page.relative_path,
                "off_centroid_paths": sorted({row.relative_path for row in off_rows}),
                "row_count": len(locations),
            }
        )
    return {
        "candidate_centroids": candidate_centroids,
        "off_centroid_entry_count": len(off_entries),
        "off_centroid_entry_cids": list(off_entries),
        "routed_paths": sorted(routed_paths),
        "samples": samples,
    }


# ---------------------------------------------------------------------------
# Fixture recipes (compact; no bulk goldens)
# ---------------------------------------------------------------------------


def _cid(nibble: str) -> str:
    return f"sha256:{nibble.lower() * 64}"


def fixture_vector_chunks() -> list[dict[str, str]]:
    """Compact two-lobe recipe used by unit tests and the sealed receipt."""

    return [
        {
            "chunk_cid": _cid("a"),
            "entry_cid": _cid("b"),
            "heading": "Oregon short title",
            "legal_id": "oul:or:statutes:1:1:1",
            "section": "1",
            "text": "Every admitted Oregon statute chunk is a durable legal section.",
            "title": "1",
        },
        {
            "chunk_cid": _cid("c"),
            "entry_cid": _cid("d"),
            "heading": "Oregon construction",
            "legal_id": "oul:or:statutes:1:1:2",
            "section": "2",
            "text": "Statutory text shall be construed according to official edition.",
            "title": "1",
        },
        {
            "chunk_cid": _cid("e"),
            "entry_cid": _cid("f"),
            "heading": "Oregon definitions",
            "legal_id": "oul:or:statutes:1:1:3",
            "section": "3",
            "text": "As used in this chapter, code means the official compiled statutes.",
            "title": "1",
        },
        {
            "chunk_cid": _cid("1"),
            "entry_cid": _cid("2"),
            "heading": "Hearing procedure",
            "legal_id": "oul:wa:statutes:34:5:1",
            "section": "1",
            "text": "Agencies shall provide notice and a contested-case hearing record.",
            "title": "34",
        },
        {
            "chunk_cid": _cid("3"),
            "entry_cid": _cid("4"),
            "heading": "Public records",
            "legal_id": "oul:wa:statutes:42:56:1",
            "section": "1",
            "text": "Each agency shall make public records available upon written request.",
            "title": "42",
        },
        {
            "chunk_cid": _cid("5"),
            "entry_cid": _cid("6"),
            "heading": "Rule making",
            "legal_id": "oul:wa:statutes:34:5:2",
            "section": "2",
            "text": "Agencies shall promulgate rules of procedure and general policy.",
            "title": "34",
        },
        {
            "chunk_cid": _cid("7"),
            "entry_cid": _cid("8"),
            "heading": "Oregon application",
            "legal_id": "oul:or:statutes:1:1:4",
            "section": "4",
            "text": "This official compiled code applies to every admitted Oregon section.",
            "title": "1",
        },
        {
            "chunk_cid": _cid("9"),
            "entry_cid": _cid("8"),
            "heading": "Oregon application continued",
            "legal_id": "oul:or:statutes:1:1:4:a",
            "section": "4a",
            "text": "Continuation of the official compiled Oregon application section.",
            "title": "1",
        },
    ]


def default_test_bounds() -> dict[str, int]:
    return {
        "entry_locator_page_size": DEFAULT_TEST_ENTRY_LOCATOR_PAGE_SIZE,
        "kmeans_iterations": DEFAULT_KMEANS_ITERATIONS,
        "max_rows_per_centroid": DEFAULT_TEST_MAX_ROWS_PER_CENTROID,
        "max_rows_per_shard": DEFAULT_TEST_MAX_ROWS_PER_SHARD,
        "max_shards_per_centroid": MAX_VECTOR_SHARDS_PER_CENTROID,
        "seed": DEFAULT_VECTOR_KMEANS_SEED,
        "target_rows_per_centroid": DEFAULT_TEST_TARGET_ROWS_PER_CENTROID,
    }


def fixture_corpus_root_cid(chunks: Sequence[Mapping[str, Any]] | None = None) -> str:
    rows = list(chunks) if chunks is not None else fixture_vector_chunks()
    return _prefixed_digest(
        content_sha256(
            canonical_json_bytes(
                {
                    "chunks": [row["chunk_cid"] for row in rows],
                    "profile": RELEASE_PROFILE,
                    "task_id": TASK_ID,
                }
            )
        )
    )


def bind_fixture_vectors(
    chunks: Sequence[Mapping[str, Any]] | None = None,
    **overrides: Any,
) -> OpenUsLawVectorBinding:
    """Bind the compact fixture recipe with tight physical test bounds."""

    params = default_test_bounds()
    params.update(overrides)
    rows = list(chunks) if chunks is not None else fixture_vector_chunks()
    corpus_root = params.pop("corpus_root_cid", fixture_corpus_root_cid(rows))
    config = params.pop("config", fixture_embedding_config())
    embedder = params.pop("embedder", None)
    device_probe = params.pop("device_probe", lambda device: str(device).startswith("cpu"))
    return bind_open_us_law_vectors_from_chunks(
        rows,
        corpus_root_cid=corpus_root,
        config=config,
        embedder=embedder,
        device_probe=device_probe,
        **params,
    )


# ---------------------------------------------------------------------------
# Receipt
# ---------------------------------------------------------------------------


def default_vector_receipt_path() -> Path:
    return Path(__file__).resolve().parents[3] / RECEIPT_RELATIVE_PATH


def software_contract_flags() -> dict[str, Any]:
    return {
        "authorizing_for_publication": AUTHORIZES_PUBLICATION,
        "authorizing_for_release": AUTHORIZES_RELEASE,
        "projection_fallback_authorizes_release": (
            PROJECTION_FALLBACK_AUTHORIZES_VECTOR_RELEASE
        ),
        "proves_software_contract_only": PROVES_SOFTWARE_CONTRACT_ONLY,
    }


def production_vector_bounds() -> dict[str, Any]:
    shared = vector_bounds_policy()
    return {
        "default_candidate_centroids": DEFAULT_CANDIDATE_CENTROIDS,
        "default_kmeans_iterations": DEFAULT_KMEANS_ITERATIONS,
        "default_kmeans_seed": DEFAULT_VECTOR_KMEANS_SEED,
        "maximum_rows_per_centroid": MAX_ROWS_PER_VECTOR_CENTROID,
        "maximum_rows_per_physical_shard": MAX_ROWS_PER_PHYSICAL_SHARD,
        "maximum_shards_per_centroid": MAX_VECTOR_SHARDS_PER_CENTROID,
        "shared_max_rows_per_physical_shard": shared["max_rows_per_physical_shard"],
        "shared_max_rows_per_vector_centroid": shared["max_rows_per_vector_centroid"],
        "shared_max_vector_shards_per_centroid": shared["max_vector_shards_per_centroid"],
        "sort_order": ROWS_SORTED_BY,
        "target_rows_per_centroid": DEFAULT_TARGET_ROWS_PER_CENTROID,
    }


def _acceptance_block() -> dict[str, bool]:
    return {
        "at_most_8192_rows_per_centroid": True,
        "at_most_two_shards_per_centroid": True,
        "dedicated_entry_to_shard_locator": True,
        "deterministic_balanced_spherical_kmeans": True,
        "entry_locator_supports_off_centroid_graph_frontier": True,
        "every_physical_shard_at_most_4096_vectors": True,
        "hierarchical_entry_routes_available": True,
        "projection_cannot_authorize_release": True,
        "shard_first_last_keys_are_not_lexical_ranges": True,
        "sorted_by_centroid_cosine_desc_then_entry_cid": True,
    }


def _cpu_probe(device: str) -> bool:
    return str(device).startswith("cpu")


def build_vector_receipt(
    *,
    binding: OpenUsLawVectorBinding | None = None,
) -> dict[str, Any]:
    """Build the sealed software-contract vector receipt."""

    demo = binding
    if demo is None:
        demo = bind_fixture_vectors(device_probe=_cpu_probe)
    query = list(demo.layout.shards[0].embeddings[0])
    off_proof = prove_entry_locator_off_centroid_hydration(
        demo, query, candidate_centroids=1
    )
    assert_rows_sorted_by_centroid_cosine_then_entry_cid(demo)
    assert_centroid_routes_bounded(demo.layout)
    pin = default_embedding_config()
    lexical_misuse = shard_first_last_keys_are_lexical_ranges(
        demo.routing_rows, demo.locations
    )
    payload: dict[str, Any] = {
        "acceptance": _acceptance_block(),
        "adr_path": ADR_PATH,
        "assignment": ASSIGNMENT,
        "authorizing_for_publication": False,
        "authorizing_for_release": False,
        "backend": {
            "default": DEFAULT_BACKEND,
            "production": PRODUCTION_BACKEND,
            "projection": PROJECTION_BACKEND,
            "projection_authorizes_release": PROJECTION_FALLBACK_AUTHORIZES_RELEASE,
            "provider": DEFAULT_PROVIDER,
        },
        "bounds": production_vector_bounds(),
        "checks": {
            "dedicated_entry_locator_present": len(demo.entry_locator_rows) >= 1,
            "demo_cluster_count": demo.cluster_count,
            "demo_entry_count": len(demo.entry_cids),
            "demo_max_rows_per_centroid": max(
                group.row_count for group in demo.layout.clusters
            ),
            "demo_max_rows_per_shard": max(shard.row_count for shard in demo.layout.shards),
            "demo_max_shards_per_centroid": max(
                group.shard_count for group in demo.layout.clusters
            ),
            "demo_off_centroid_entry_count": off_proof["off_centroid_entry_count"],
            "demo_shard_count": demo.shard_count,
            "demo_shared_entry_located": len(demo.locate_entry(_cid("8"))) == 2,
            "demo_vector_count": demo.vector_count,
            "empty_cluster_policy": EMPTY_CLUSTER_POLICY,
            "entry_locator_index_covers_every_entry": all(
                demo.entry_locator_index().covers(entry_cid)
                for entry_cid in demo.entry_cids
            ),
            "every_chunk_once": sorted(demo.chunk_cids)
            == sorted(row["chunk_cid"] for row in fixture_vector_chunks()),
            "hierarchical_entry_routes_present": demo.entry_route_index is not None,
            "kmeans_iterations": demo.layout.kmeans_iterations,
            "layout_seed": demo.layout_seed,
            "membership_hash": demo.membership_hash,
            "objective": demo.objective,
            "pinned_dimension": PINNED_DIMENSION,
            "pinned_max_tokens": PINNED_MAX_TOKENS,
            "pinned_model_id": PINNED_MODEL_ID,
            "pinned_model_revision": PINNED_MODEL_REVISION,
            "pinned_normalization": PINNED_NORMALIZATION,
            "pinned_pooling": PINNED_POOLING,
            "production_max_rows_per_centroid": MAX_ROWS_PER_VECTOR_CENTROID,
            "production_max_rows_per_shard": MAX_ROWS_PER_PHYSICAL_SHARD,
            "production_max_shards_per_centroid": MAX_VECTOR_SHARDS_PER_CENTROID,
            "rows_sorted_by": ROWS_SORTED_BY,
            "shard_first_last_keys_are_lexical_ranges": lexical_misuse,
            "vector_root_cid": demo.vector_root_cid,
        },
        "demo": {
            "authorizing_for_release": False,
            "backend": PROJECTION_BACKEND,
            "cluster_count": demo.cluster_count,
            "config_cid": demo.config_cid,
            "corpus_root_cid": demo.corpus_root_cid,
            "entry_cids": list(demo.entry_cids),
            "entry_locator_page_count": len(demo.entry_locator_rows),
            "membership_hash": demo.membership_hash,
            "model_cid": demo.model_cid,
            "objective": demo.objective,
            "off_centroid_entry_cids": list(off_proof["off_centroid_entry_cids"]),
            "real_inference": False,
            "shard_count": demo.shard_count,
            "vector_count": demo.vector_count,
            "vector_root_cid": demo.vector_root_cid,
        },
        "description": (
            "Software-contract receipt for OUL-029. Deterministic balanced "
            "spherical k-means yields at most 8192 rows and two shards per "
            "centroid. Every physical shard has at most 4096 vectors sorted by "
            "descending centroid cosine then entry CID. A dedicated "
            "entry-to-shard locator supports off-centroid graph frontier "
            "hydration. Projection output cannot authorize release. This "
            "receipt does not claim the live exact-51 corpus has been clustered."
        ),
        "device": {
            "default": DEFAULT_DEVICE,
            "precision": DEFAULT_PRECISION,
        },
        "empty_cluster_policy": EMPTY_CLUSTER_POLICY,
        "entry_locator": {
            "directory": VECTOR_ENTRY_LOCATOR_DIR,
            "hierarchical_routes_schema": HIERARCHICAL_ROUTE_SCHEMA_VERSION,
            "key": ENTRY_LOCATOR_KEY,
            "required": True,
            "route_directory": VECTOR_ENTRY_ROUTE_DIR,
        },
        "exact_51_seed_row_lower_bound": EXACT_51_SEED_ROW_LOWER_BOUND,
        "goal_id": GOAL_ID,
        "model_pin": {
            "dimension": PINNED_DIMENSION,
            "license": PINNED_MODEL_LICENSE,
            "max_tokens": PINNED_MAX_TOKENS,
            "model_id": PINNED_MODEL_ID,
            "model_revision": PINNED_MODEL_REVISION,
            "normalization": PINNED_NORMALIZATION,
            "pooling": PINNED_POOLING,
            "vector_space_id": default_vector_space_id(),
        },
        "producer": PRODUCER,
        "program_id": PROGRAM_ID,
        "projection_fallback_authorizes_release": False,
        "proves_software_contract_only": True,
        "release_profile": RELEASE_PROFILE,
        "repairs": {
            "area_id": "centroid_routed_vectors",
            "owner_task": TASK_ID,
            "required": [
                (
                    "Cluster normalized vectors with deterministic balanced "
                    "spherical k-means and record seed, iterations, objective, "
                    "empty-cluster handling, and membership hashes."
                ),
                (
                    "Cap every centroid at 8192 rows and two physical shards, "
                    "and every physical shard at 4096 vectors."
                ),
                (
                    "Sort every physical shard by descending centroid cosine "
                    "then stable entry CID."
                ),
                (
                    "Expose a dedicated entry-to-shard locator so off-centroid "
                    "graph frontier nodes hydrate without treating cosine-sorted "
                    "shard first/last keys as lexical CID ranges."
                ),
            ],
        },
        "rows_sorted_by": ROWS_SORTED_BY,
        "schema_version": RECEIPT_SCHEMA_VERSION,
        "sealed_at": RECEIPT_SEALED_AT,
        "task_id": TASK_ID,
        "vector_space_id": pin.vector_space_id,
    }
    payload.update(software_contract_flags())
    payload["receipt_sha256"] = content_sha256(
        canonical_json_bytes(
            {key: value for key, value in payload.items() if key != "receipt_sha256"}
        )
    )
    return payload


def write_vector_receipt(path: PathLike | None = None) -> Path:
    target = Path(path) if path is not None else default_vector_receipt_path()
    payload = build_vector_receipt()
    write_json_atomic(target, payload)
    return target


def load_vector_receipt(path: PathLike | None = None) -> dict[str, Any]:
    target = Path(path) if path is not None else default_vector_receipt_path()
    if not target.is_file():
        raise VectorReceiptError(f"vector receipt not found: {target}")
    payload = json.loads(target.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise VectorReceiptError("vector receipt root must be an object")
    return dict(payload)


def assert_vector_receipt(payload: Mapping[str, Any]) -> None:
    """Fail closed if the receipt would authorize projection or a wrong pin."""

    if payload.get("task_id") != TASK_ID:
        raise VectorReceiptError(f"receipt task_id must be {TASK_ID!r}")
    if payload.get("schema_version") != RECEIPT_SCHEMA_VERSION:
        raise VectorReceiptError(
            f"receipt schema_version must be {RECEIPT_SCHEMA_VERSION!r}"
        )
    if payload.get("authorizing_for_release") is True:
        raise VectorReleaseAuthorizationError(
            "vector receipt cannot authorize release"
        )
    if payload.get("authorizing_for_publication") is True:
        raise VectorReleaseAuthorizationError(
            "vector receipt cannot authorize publication"
        )
    if payload.get("projection_fallback_authorizes_release") is True:
        raise VectorReleaseAuthorizationError(
            "projection fallback cannot authorize vector release"
        )
    pin = payload.get("model_pin") or {}
    if not isinstance(pin, Mapping):
        raise VectorReceiptError("receipt model_pin must be a mapping")
    if pin.get("model_id") != PINNED_MODEL_ID:
        raise VectorReceiptError("receipt model_id is not the sealed pin")
    if pin.get("model_revision") != PINNED_MODEL_REVISION:
        raise VectorReceiptError("receipt model_revision is not the sealed pin")
    if pin.get("dimension") != PINNED_DIMENSION:
        raise VectorReceiptError("receipt dimension is not 384")
    bounds = payload.get("bounds") or {}
    if not isinstance(bounds, Mapping):
        raise VectorReceiptError("receipt bounds must be a mapping")
    if bounds.get("maximum_rows_per_physical_shard") != MAX_ROWS_PER_PHYSICAL_SHARD:
        raise VectorReceiptError("receipt physical shard bound must be 4096")
    if bounds.get("maximum_rows_per_centroid") != MAX_ROWS_PER_VECTOR_CENTROID:
        raise VectorReceiptError("receipt centroid row bound must be 8192")
    if bounds.get("maximum_shards_per_centroid") != MAX_VECTOR_SHARDS_PER_CENTROID:
        raise VectorReceiptError("receipt centroid shard bound must be 2")
    if payload.get("rows_sorted_by") != ROWS_SORTED_BY:
        raise VectorReceiptError(
            f"receipt rows_sorted_by must be {ROWS_SORTED_BY!r}"
        )
    acceptance = payload.get("acceptance") or {}
    if not isinstance(acceptance, Mapping):
        raise VectorReceiptError("receipt acceptance must be a mapping")
    for key, expected in _acceptance_block().items():
        if acceptance.get(key) is not expected:
            raise VectorReceiptError(f"receipt acceptance.{key} must be {expected}")
    if payload.get("proves_software_contract_only") is not True:
        raise VectorReceiptError("receipt must prove the software contract only")


__all__ = [
    "ASSIGNMENT",
    "DEFAULT_CANDIDATE_CENTROIDS",
    "DEFAULT_TARGET_ROWS_PER_CENTROID",
    "DEFAULT_VECTOR_KMEANS_SEED",
    "EMPTY_CLUSTER_POLICY",
    "ENTRY_LOCATOR_KEY",
    "GOAL_ID",
    "MAX_ROWS_PER_PHYSICAL_SHARD",
    "MAX_ROWS_PER_VECTOR_CENTROID",
    "MAX_VECTOR_SHARDS_PER_CENTROID",
    "PRIMARY_KEY",
    "PRODUCER",
    "PROGRAM_ID",
    "RECEIPT_SCHEMA_VERSION",
    "RELEASE_PROFILE",
    "ROWS_SORTED_BY",
    "SCHEMA_VERSION",
    "TASK_ID",
    "VECTOR_ENTRY_LOCATOR_DIR",
    "CorpusParentLink",
    "ManifestReadyDescriptor",
    "OpenUsLawVectorBinding",
    "OpenUsLawVectorError",
    "VectorBindingError",
    "VectorCoverageError",
    "VectorLocatorError",
    "VectorOrderingError",
    "VectorReceiptError",
    "VectorReleaseAuthorizationError",
    "VectorRootReconcileError",
    "VectorRouteBoundError",
    "VectorShardLocation",
    "assert_centroid_routes_bounded",
    "assert_every_chunk_once",
    "assert_rows_sorted_by_centroid_cosine_then_entry_cid",
    "assert_vector_receipt",
    "bind_fixture_vectors",
    "bind_open_us_law_vectors",
    "bind_open_us_law_vectors_from_chunks",
    "build_entry_locator_rows",
    "build_entry_locations",
    "build_layout_root_cid",
    "build_location_map",
    "build_manifest_descriptors",
    "build_membership_hash",
    "build_model_cid",
    "build_open_us_law_centroid_layout",
    "build_parent_links",
    "build_vector_receipt",
    "default_test_bounds",
    "default_vector_receipt_path",
    "embeddings_to_vector_records",
    "fixture_vector_chunks",
    "layout_objective",
    "load_vector_receipt",
    "production_vector_bounds",
    "prove_direct_cid_off_centroid_fetch",
    "prove_entry_locator_off_centroid_hydration",
    "reconcile_roots",
    "route_open_us_law_shards",
    "resort_layout_by_centroid_cosine_then_entry_cid",
    "select_off_centroid_entry_cids",
    "select_off_centroid_keys",
    "shard_first_last_keys_are_lexical_ranges",
    "write_vector_receipt",
]
