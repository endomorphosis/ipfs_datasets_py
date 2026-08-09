"""Bind US Code vectors to centroid and direct-CID routes (USCIR-019).

This module is the legal-domain adapter between:

* pinned embeddings from :mod:`uscode_embeddings` (USCIR-017);
* domain-neutral centroid layout from
  :mod:`ipfs_datasets_py.retrieval.hf_graphrag.vectors` (USCIR-018); and
* direct CID-to-vector locators from
  :mod:`ipfs_datasets_py.retrieval.hf_graphrag.locators` (USCIR-011).

Design invariants
-----------------
* Every embedded chunk appears in **exactly one** physical vector shard
  (row conservation and uniqueness).
* Dense search uses bounded centroid routes (≤4,096 rows/shard, ≤8,192
  rows and ≤2 shards per centroid).
* Direct CID fetch resolves any durable vector key (chunk CID) to its
  containing data shard even when that shard is off the query-selected
  centroid set (graph-frontier / off-centroid hydration).
* Model revision, config CID, vector-space id, corpus parent root, and
  layout seed all reconcile on the sealed binding receipt.
* Corpus parent links (``chunk_cid`` → ``entry_cid``) are recorded for
  every vector row that has a parent retrieval identity.
* No network I/O; unit tests use compact sealed recipes only.
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final, Optional, Union

from ipfs_datasets_py.processors.legal_data.uscode_embeddings import (
    DEFAULT_MODEL_ID,
    DEFAULT_MODEL_REVISION,
    DEFAULT_NORMALIZATION,
    DEFAULT_POOLING,
    EmbeddingGenerationResult,
    EmbeddingRecord,
    UscodeEmbeddingConfig,
    default_embedding_config,
    generate_uscode_embeddings,
    reject_placeholder_model_ref,
)
from ipfs_datasets_py.processors.legal_data.uscode_release_schema import (
    PositionalIdentityError,
    reject_positional_durable_identity,
    require_immutable_model_ref,
    validate_digest,
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
    canonical_json_dumps,
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
    VECTOR_DATA_DIR,
    VECTOR_INDEX_PATH,
    VECTOR_LAYOUT_SCHEMA_VERSION,
    VECTOR_ROUTING_SCHEMA_VERSION,
    VectorClusterLayout,
    VectorRecord,
    VectorShardRoute,
    build_centroid_routed_vector_layout,
    route_vector_shards,
    validate_vector_layout,
    vector_bounds_policy,
)

# ---------------------------------------------------------------------------
# Identity
# ---------------------------------------------------------------------------

SCHEMA_VERSION: Final = "uscode-vectors-v1"
FIXTURE_SCHEMA_VERSION: Final = "uscode-vector-routes-v1"
TASK_ID: Final = "USCIR-019"
GOAL_ID: Final = "USCIR-G050"
RELEASE_PROFILE: Final = "publicus-ir-graphrag/v2"
PRODUCER: Final = "uscode_vectors.py"

VECTOR_ENTRY_LOCATOR_DIR: Final = "indexes/vector_entry_locator"
VECTOR_KEY_FIELD: Final = "chunk_cid"
PRIMARY_KEY: Final = "chunk_cid"
PARENT_KEY: Final = "entry_cid"

PathLike = Union[str, Path]
JsonMapping = Mapping[str, Any]


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class UscodeVectorError(ValueError):
    """Base error for US Code vector binding failures."""

    code: str = "uscode_vector_error"

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        if code is not None:
            self.code = code

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "kind": "error", "message": str(self)}


class VectorBindingError(UscodeVectorError):
    """Raised when embeddings cannot be bound to a vector layout."""

    code = "binding_invalid"


class VectorCoverageError(UscodeVectorError):
    """Raised when chunk conservation or uniqueness fails."""

    code = "coverage_invalid"


class VectorRouteBoundError(UscodeVectorError):
    """Raised when centroid or shard physical bounds are violated."""

    code = "route_bound_exceeded"


class VectorRootReconcileError(UscodeVectorError):
    """Raised when model/config/corpus/layout roots do not reconcile."""

    code = "root_reconcile_failed"


class VectorLocatorError(UscodeVectorError):
    """Raised when direct CID vector location fails."""

    code = "locator_failed"


class VectorFixtureError(UscodeVectorError):
    """Raised when the sealed vector-routes fixture is malformed."""

    code = "fixture_invalid"


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
    return text


def build_model_cid(
    *,
    model_id: str,
    model_revision: str,
    vector_space_id: str,
) -> str:
    """Content-address the immutable model pin surface."""

    model, revision = reject_placeholder_model_ref(
        model_id=model_id, model_revision=model_revision
    )
    space = _require_non_empty_str(vector_space_id, "vector_space_id", maximum=512)
    payload = {
        "model_id": model,
        "model_revision": revision,
        "vector_space_id": space,
    }
    return "sha256:" + content_sha256(canonical_json_bytes(payload))


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
    return "sha256:" + content_sha256(canonical_json_bytes(structural))


def _synthetic_shard_digest(relative_path: str, row_count: int) -> str:
    """Deterministic placeholder digest for in-memory (not-yet-written) shards."""

    return content_sha256(
        f"uscode-vector-shard:{relative_path}:rows={row_count}"
    )


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

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "vector_key", _durable_key(self.vector_key, "vector_key")
        )
        object.__setattr__(
            self, "chunk_cid", _durable_key(self.chunk_cid, "chunk_cid")
        )
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

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
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

    def to_locator_row(self) -> LocatorRow:
        """Project this location as a singleton inclusive key-range locator."""

        return LocatorRow(
            first_key=self.vector_key,
            last_key=self.vector_key,
            relative_path=self.relative_path,
            sha256=self.sha256 or _synthetic_shard_digest(self.relative_path, 1),
            size_bytes=self.size_bytes,
            row_count=1,
            shard_id=self.global_shard_id,
            kind=KIND_VECTORS,
            schema_version=LOCATOR_SCHEMA_VERSION,
            content_cid=self.content_cid,
            metadata={
                "chunk_cid": self.chunk_cid,
                "chunk_in_cluster": self.chunk_in_cluster,
                "cluster_id": self.cluster_id,
                "entry_cid": self.entry_cid,
                "row_offset": self.row_offset,
                "vector_key": self.vector_key,
            },
        )


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
        object.__setattr__(
            self, "sha256", normalize_sha256(self.sha256, name="sha256")
        )
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
class UscodeVectorBinding:
    """Complete US Code vector binding: centroid routes + direct CID map."""

    layout: VectorClusterLayout
    routing_rows: tuple[dict[str, Any], ...]
    locations: Mapping[str, VectorShardLocation]
    parent_links: tuple[CorpusParentLink, ...]
    model_id: str
    model_revision: str
    vector_space_id: str
    config_cid: str
    model_cid: str
    vector_root_cid: str
    layout_seed: int
    corpus_root_cid: Optional[str] = None
    embedding_config: Optional[UscodeEmbeddingConfig] = None
    entry_locator_rows: tuple[LocatorRow, ...] = ()
    descriptors: tuple[ManifestReadyDescriptor, ...] = ()
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
        if len(self.locations) != self.layout.total_rows:
            raise VectorCoverageError(
                f"location map size {len(self.locations)} != layout "
                f"total_rows {self.layout.total_rows}"
            )
        model_id, model_revision = require_immutable_model_ref(
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

    def location_for(self, vector_key: str) -> VectorShardLocation:
        """Return the exact shard location for a durable vector key."""

        key = _durable_key(vector_key, "vector_key")
        try:
            return self.locations[key]
        except KeyError as exc:
            raise MissingKeyError(
                f"vector key {key!r} is not covered by any vector shard"
            ) from exc

    def locate_vector(self, vector_key: str) -> LocatorHit:
        """Direct CID fetch: resolve a vector key to its data-shard locator hit.

        Works for every bound key, including those whose physical shard is
        outside the query-selected centroid set (off-centroid graph frontier).
        """

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
            metadata={
                "chunk_cid": location.chunk_cid,
                "chunk_in_cluster": location.chunk_in_cluster,
                "cluster_id": location.cluster_id,
                "entry_cid": location.entry_cid,
                "row_offset": location.row_offset,
                "vector_key": location.vector_key,
            },
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

    def containing_vector_artifacts(
        self,
        vector_keys: Sequence[str],
        *,
        strict: bool = True,
    ) -> tuple[LocatorRow, ...]:
        """Minimal unique data-shard set required to hydrate *vector_keys*."""

        hits = self.locate_vectors(vector_keys, strict=strict)
        unique: dict[tuple[int, str], LocatorRow] = {}
        for hit in hits:
            # Promote row_count to the full shard size when known from layout.
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

    def entry_locator_index(self) -> KeyLocatorIndex:
        """Bounded CID-range index over entry-locator pages (packaging surface)."""

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

    def locations_for_entry_cid(self, entry_cid: str) -> tuple[VectorShardLocation, ...]:
        """Return all vector locations whose corpus parent is *entry_cid*."""

        parent = _durable_key(entry_cid, "entry_cid")
        matches = [
            loc
            for loc in self.locations.values()
            if loc.entry_cid == parent
        ]
        return tuple(sorted(matches, key=lambda item: item.vector_key))

    def receipt(self) -> dict[str, Any]:
        """Compact binding receipt for manifests / audit logs."""

        return {
            "assignment": self.layout.assignment,
            "cluster_count": self.cluster_count,
            "config_cid": self.config_cid,
            "corpus_root_cid": self.corpus_root_cid,
            "dimension": self.layout.dimension,
            "goal_id": self.goal_id,
            "layout_seed": self.layout_seed,
            "max_rows_per_centroid": self.layout.max_rows_per_centroid,
            "max_rows_per_shard": self.layout.max_rows_per_shard,
            "max_shards_per_centroid": self.layout.max_shards_per_centroid,
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
        records = tuple(
            embeddings.embeddings[cid]
            for cid in sorted(embeddings.embeddings)
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
                # Bare vector sequence — incomplete pin; fail closed.
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
    model_id = str(value.get("model_id") or DEFAULT_MODEL_ID)
    model_revision = str(value.get("model_revision") or DEFAULT_MODEL_REVISION)
    pooling = str(value.get("pooling") or DEFAULT_POOLING)
    normalization = str(value.get("normalization") or DEFAULT_NORMALIZATION)
    vector_space_id = str(value.get("vector_space_id") or "").strip()
    if not vector_space_id:
        from ipfs_datasets_py.processors.legal_data.uscode_embeddings import (
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
        config_cid = "sha256:" + content_sha256(
            canonical_json_bytes(
                {
                    "model_id": model_id,
                    "model_revision": model_revision,
                    "vector_space_id": vector_space_id,
                }
            )
        )
    input_hash = str(value.get("input_hash") or "").strip()
    if not input_hash:
        input_hash = content_sha256(f"input:{chunk_cid}")
    l2 = float(value.get("l2_norm") or 0.0)
    if l2 <= 0.0:
        l2 = math.sqrt(sum(float(x) * float(x) for x in embedding))
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
        entry_cid=value.get("entry_cid"),
        chunk_id=value.get("chunk_id"),
    )


def embeddings_to_vector_records(
    records: Sequence[EmbeddingRecord],
) -> tuple[VectorRecord, ...]:
    """Project trusted embedding records into domain-neutral vector rows.

    The durable vector primary key is ``chunk_cid`` (unique per embedded
    chunk). Parent ``entry_cid`` is preserved in metadata for corpus links.
    """

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


# ---------------------------------------------------------------------------
# Locator page construction (packaging surface)
# ---------------------------------------------------------------------------


def build_entry_locator_rows(
    locations: Mapping[str, VectorShardLocation],
    *,
    max_keys_per_page: int = MAX_ROWS_PER_PHYSICAL_SHARD,
    locator_dir: str = VECTOR_ENTRY_LOCATOR_DIR,
) -> tuple[LocatorRow, ...]:
    """Partition sorted vector keys into bounded entry-locator pages.

    Each page covers an inclusive ``[first_key, last_key]`` range of durable
    vector keys and points at a compact locator artifact.  Lookup against the
    resulting :class:`KeyLocatorIndex` identifies the page that holds the
    exact ``vector_key → data-shard`` mapping; the in-memory binding resolves
    the data shard in one step via :meth:`UscodeVectorBinding.locate_vector`.
    """

    if not locations:
        return ()
    max_keys = _require_positive_int(max_keys_per_page, "max_keys_per_page")
    if max_keys > MAX_ROWS_PER_PHYSICAL_SHARD:
        raise VectorRouteBoundError(
            f"max_keys_per_page={max_keys} exceeds {MAX_ROWS_PER_PHYSICAL_SHARD}"
        )
    directory = normalize_relative_artifact_path(locator_dir)
    ordered_keys = sorted(locations)
    rows: list[LocatorRow] = []
    for page_index, offset in enumerate(range(0, len(ordered_keys), max_keys)):
        group = ordered_keys[offset : offset + max_keys]
        relative = f"{directory}/part-{page_index:06d}.parquet"
        # Page digest binds the exact key→path mapping for this page.
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


# ---------------------------------------------------------------------------
# Location map from layout
# ---------------------------------------------------------------------------


def build_location_map(
    layout: VectorClusterLayout,
    *,
    records: Sequence[EmbeddingRecord],
    descriptors: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, VectorShardLocation]:
    """Build the exact ``vector_key → shard location`` map from a layout."""

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
                content_cid=str(content_cid) if content_cid else None,
                dimension=shard.dimension,
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
    """Emit corpus parent links for chunks that declare an ``entry_cid``."""

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


def build_manifest_descriptors(
    layout: VectorClusterLayout,
    *,
    routing_rows: Sequence[Mapping[str, Any]],
    entry_locator_rows: Sequence[LocatorRow],
    descriptors: Mapping[str, Mapping[str, Any]] | None = None,
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
                    "global_shard_id": shard.global_shard_id,
                },
            )
        )
    # Routing index descriptor.
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


# ---------------------------------------------------------------------------
# Bound validation
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
        if group.shard_count > layout.max_shards_per_centroid:
            raise VectorRouteBoundError(
                f"cluster {group.cluster_id} has {group.shard_count} shards; "
                f"exceeds {layout.max_shards_per_centroid}"
            )
        for shard in group.shards:
            if shard.row_count > layout.max_rows_per_shard:
                raise VectorRouteBoundError(
                    f"shard {shard.relative_path} has {shard.row_count} rows; "
                    f"exceeds {layout.max_rows_per_shard}"
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
    validate_vector_layout(layout, expected_entry_cids=expected)


def reconcile_roots(
    binding: UscodeVectorBinding,
    *,
    expected_model_id: str | None = None,
    expected_model_revision: str | None = None,
    expected_config_cid: str | None = None,
    expected_vector_space_id: str | None = None,
    expected_corpus_root_cid: str | None = None,
    expected_layout_seed: int | None = None,
    expected_vector_root_cid: str | None = None,
) -> dict[str, Any]:
    """Reconcile model/config/corpus/layout roots; fail closed on drift."""

    checks: dict[str, Any] = {
        "config_cid": binding.config_cid,
        "corpus_root_cid": binding.corpus_root_cid,
        "layout_seed": binding.layout_seed,
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

    # Internal consistency: recompute model/layout digests.
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
# Main bind API
# ---------------------------------------------------------------------------


def bind_uscode_vectors(
    embeddings: (
        EmbeddingGenerationResult
        | Mapping[str, EmbeddingRecord | Mapping[str, Any] | Sequence[float]]
        | Sequence[EmbeddingRecord | Mapping[str, Any]]
    ),
    *,
    corpus_root_cid: str | None = None,
    config: UscodeEmbeddingConfig | None = None,
    seed: int = DEFAULT_VECTOR_KMEANS_SEED,
    max_rows_per_shard: int = MAX_ROWS_PER_PHYSICAL_SHARD,
    max_shards_per_centroid: int = MAX_VECTOR_SHARDS_PER_CENTROID,
    max_rows_per_centroid: int | None = None,
    target_rows_per_centroid: int = DEFAULT_TARGET_ROWS_PER_CENTROID,
    kmeans_iterations: int = DEFAULT_KMEANS_ITERATIONS,
    data_dir: str = VECTOR_DATA_DIR,
    entry_locator_page_size: int = MAX_ROWS_PER_PHYSICAL_SHARD,
    shard_descriptors: Mapping[str, Mapping[str, Any]] | None = None,
) -> UscodeVectorBinding:
    """Bind trusted US Code embeddings to centroid routes and direct-CID maps.

    Parameters
    ----------
    embeddings:
        Trusted embedding records (generator result, mapping, or sequence).
    corpus_root_cid:
        Optional sealed corpus root digest to bind as parent of the vector
        index. When provided it is recorded and reconciled on the receipt.
    config:
        Optional embedding pin; when omitted the pin is taken from the first
        embedding record (all records must share one pin).
    """

    records = _embedding_records_from_input(embeddings)
    chunk_cids = [rec.chunk_cid for rec in records]

    # Pin consistency across the closed embedding set.
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

    model_id, model_revision = require_immutable_model_ref(
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
    corpus_root: Optional[str] = None
    if corpus_root_cid is not None and str(corpus_root_cid).strip():
        corpus_root = validate_digest(corpus_root_cid, name="corpus_root_cid")

    binding = UscodeVectorBinding(
        layout=layout,
        routing_rows=routing_rows,
        locations=locations,
        parent_links=parent_links,
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
    )
    # Self-reconcile computed roots.
    reconcile_roots(
        binding,
        expected_model_id=model_id,
        expected_model_revision=model_revision,
        expected_config_cid=config_cid,
        expected_vector_space_id=vector_space_id,
        expected_corpus_root_cid=corpus_root,
        expected_layout_seed=seed,
        expected_vector_root_cid=vector_root_cid,
    )
    return binding


def bind_uscode_vectors_from_chunks(
    chunks: Sequence[Mapping[str, Any]],
    *,
    corpus_root_cid: str | None = None,
    config: UscodeEmbeddingConfig | None = None,
    seed: int = DEFAULT_VECTOR_KMEANS_SEED,
    max_rows_per_shard: int = MAX_ROWS_PER_PHYSICAL_SHARD,
    max_shards_per_centroid: int = MAX_VECTOR_SHARDS_PER_CENTROID,
    max_rows_per_centroid: int | None = None,
    target_rows_per_centroid: int = DEFAULT_TARGET_ROWS_PER_CENTROID,
    kmeans_iterations: int = DEFAULT_KMEANS_ITERATIONS,
    entry_locator_page_size: int = MAX_ROWS_PER_PHYSICAL_SHARD,
) -> UscodeVectorBinding:
    """Embed admitted chunks with the sealed local backend, then bind routes."""

    pin = config or default_embedding_config()
    result = generate_uscode_embeddings(chunks, config=pin)
    return bind_uscode_vectors(
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


def select_off_centroid_keys(
    binding: UscodeVectorBinding,
    query_embedding: Sequence[float],
    *,
    candidate_centroids: int = 1,
) -> tuple[str, ...]:
    """Return vector keys whose data shards are outside the centroid route set.

    Used by tests and graph-frontier walkers to prove direct CID fetch works
    for nodes that dense routing would not have selected.
    """

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
    binding: UscodeVectorBinding,
    query_embedding: Sequence[float],
    *,
    candidate_centroids: int = 1,
) -> dict[str, Any]:
    """Prove direct CID locate works for at least one off-centroid key.

    Raises :class:`VectorLocatorError` when the layout has no off-centroid
    keys for the given probe budget (e.g. single-shard corpora).
    """

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
# Fixture helpers (compact recipes)
# ---------------------------------------------------------------------------


def _fixture_chunk(
    *,
    nibble: str,
    text: str,
    title: str,
    section: str,
    legal_id: str,
    heading: str,
) -> dict[str, Any]:
    """Build a compact admitted-chunk recipe row with durable hex CIDs."""

    n = nibble.lower()
    chunk_cid = f"sha256:{n * 64}"
    # Parent entry uses a different nibble so parent links are non-trivial.
    parent_nibble = format((int(n, 16) + 1) % 16, "x")
    entry_cid = f"sha256:{parent_nibble * 64}"
    return {
        "chunk_cid": chunk_cid,
        "entry_cid": entry_cid,
        "heading": heading,
        "legal_id": legal_id,
        "section": section,
        "text": text,
        "title": title,
    }


def build_default_vector_routes_fixture_payload(
    *,
    seed: int = DEFAULT_VECTOR_KMEANS_SEED,
    include_realized: bool = True,
) -> dict[str, Any]:
    """Build the sealed unit-test fixture payload (compact recipes only)."""

    # Two semantic lobes (patent vs FOIA language) so centroid routing and
    # off-centroid direct CID fetch are both exercised without bulk goldens.
    chunks = [
        _fixture_chunk(
            nibble="a",
            text="Whoever invents or discovers any new and useful process machine manufacture.",
            title="35",
            section="101",
            legal_id="usc:us:35:101",
            heading="Inventions patentable",
        ),
        _fixture_chunk(
            nibble="b",
            text="A patent may not be obtained if the differences would have been obvious.",
            title="35",
            section="103",
            legal_id="usc:us:35:103",
            heading="Conditions for patentability; non-obvious subject matter",
        ),
        _fixture_chunk(
            nibble="c",
            text="The specification shall contain a written description of the invention.",
            title="35",
            section="112",
            legal_id="usc:us:35:112",
            heading="Specification",
        ),
        _fixture_chunk(
            nibble="d",
            text="Each agency shall make available to the public information as follows.",
            title="5",
            section="552",
            legal_id="usc:us:5:552",
            heading="Public information; agency rules, opinions, orders, records",
        ),
        _fixture_chunk(
            nibble="e",
            text="This section does not apply to matters that are specifically authorized.",
            title="5",
            section="552",
            legal_id="usc:us:5:552:b",
            heading="FOIA exemptions",
        ),
        _fixture_chunk(
            nibble="f",
            text="Agencies shall promulgate rules of procedure and statements of policy.",
            title="5",
            section="553",
            legal_id="usc:us:5:553",
            heading="Rule making",
        ),
        _fixture_chunk(
            nibble="1",
            text="Patent eligibility excludes laws of nature natural phenomena and abstract ideas.",
            title="35",
            section="101",
            legal_id="usc:us:35:101:note",
            heading="Judicial exceptions",
        ),
        _fixture_chunk(
            nibble="2",
            text="Freedom of information requests shall be processed within twenty days.",
            title="5",
            section="552",
            legal_id="usc:us:5:552:a6",
            heading="Time limits",
        ),
    ]
    test_bounds = {
        "kmeans_iterations": DEFAULT_KMEANS_ITERATIONS,
        "max_rows_per_centroid": 4,
        "max_rows_per_shard": 2,
        "max_shards_per_centroid": 2,
        "seed": int(seed),
        "target_rows_per_centroid": 3,
        "entry_locator_page_size": 4,
    }
    corpus_root_cid = "sha256:" + content_sha256(
        canonical_json_bytes(
            {
                "chunks": [c["chunk_cid"] for c in chunks],
                "profile": RELEASE_PROFILE,
            }
        )
    )
    expected: dict[str, Any] = {
        "chunk_count": len(chunks),
        "max_rows_per_centroid": test_bounds["max_rows_per_centroid"],
        "max_rows_per_shard": test_bounds["max_rows_per_shard"],
        "max_shards_per_centroid": test_bounds["max_shards_per_centroid"],
        "parent_link_count": len(chunks),  # every fixture chunk has entry_cid
        "primary_key": PRIMARY_KEY,
        "rows_sorted_by": ROWS_SORTED_BY,
        "seed": int(seed),
        "unique_chunk_cids": sorted(c["chunk_cid"] for c in chunks),
    }
    cases = [
        {
            "case_id": "every-chunk-exactly-once",
            "expect": {
                "chunk_count": len(chunks),
                "unique": True,
            },
            "kind": "coverage",
        },
        {
            "case_id": "centroid-routes-bounded",
            "expect": {
                "max_rows_per_centroid": test_bounds["max_rows_per_centroid"],
                "max_rows_per_shard": test_bounds["max_rows_per_shard"],
                "max_shards_per_centroid": test_bounds["max_shards_per_centroid"],
            },
            "kind": "bounds",
        },
        {
            "case_id": "direct-cid-off-centroid",
            "expect": {
                "candidate_centroids": 1,
                "off_centroid_min": 1,
            },
            "kind": "direct_cid",
        },
        {
            "case_id": "roots-revisions-reconcile",
            "expect": {
                "reconciled": True,
            },
            "kind": "reconcile",
        },
        {
            "case_id": "parent-links-present",
            "expect": {
                "parent_link_count": len(chunks),
            },
            "kind": "parent_links",
        },
    ]
    if include_realized:
        binding = bind_uscode_vectors_from_chunks(
            chunks,
            corpus_root_cid=corpus_root_cid,
            seed=int(seed),
            max_rows_per_shard=int(test_bounds["max_rows_per_shard"]),
            max_shards_per_centroid=int(test_bounds["max_shards_per_centroid"]),
            max_rows_per_centroid=int(test_bounds["max_rows_per_centroid"]),
            target_rows_per_centroid=int(test_bounds["target_rows_per_centroid"]),
            kmeans_iterations=int(test_bounds["kmeans_iterations"]),
            entry_locator_page_size=int(test_bounds["entry_locator_page_size"]),
        )
        expected.update(
            {
                "cluster_count": binding.cluster_count,
                "config_cid": binding.config_cid,
                "corpus_root_cid": binding.corpus_root_cid,
                "layout_digest": binding.vector_root_cid,
                "model_cid": binding.model_cid,
                "model_id": binding.model_id,
                "model_revision": binding.model_revision,
                "shard_count": binding.shard_count,
                "vector_space_id": binding.vector_space_id,
            }
        )
    pin = default_embedding_config()
    return {
        "acceptance": {
            "centroid_routes_bounded": True,
            "direct_cid_fetch_locates_off_centroid_graph_nodes": True,
            "every_embedded_chunk_appears_exactly_once": True,
            "roots_and_revisions_reconcile": True,
        },
        "assignment": ASSIGNMENT,
        "bounds": vector_bounds_policy(),
        "cases": cases,
        "chunks": chunks,
        "corpus_root_cid": corpus_root_cid,
        "default_pin": {
            "dimension": pin.dimension,
            "model_id": pin.model_id,
            "model_revision": pin.model_revision,
            "normalization": pin.normalization,
            "pooling": pin.pooling,
            "vector_space_id": pin.vector_space_id,
        },
        "description": (
            "Compact US Code vector-route recipes for USCIR-019. Embeddings "
            "are regenerated by the sealed local backend; centroid layout and "
            "direct-CID locators are derived deterministically. No bulk "
            "embedding golden dumps."
        ),
        "expected": expected,
        "goal_id": GOAL_ID,
        "notes": (
            "Recipe form: chunks + bounds + case expectations only. Expand "
            "via bind_uscode_vectors_from_chunks() / run_vector_route_case()."
        ),
        "producer": PRODUCER,
        "release_profile": RELEASE_PROFILE,
        "schema_version": FIXTURE_SCHEMA_VERSION,
        "task_id": TASK_ID,
        "test_bounds": test_bounds,
    }


def default_vector_routes_fixture_path() -> Path:
    return (
        Path(__file__).resolve().parents[3]
        / "tests"
        / "fixtures"
        / "legal_ir"
        / "uscode_vector_routes.json"
    )


def load_vector_routes_fixture_payload(
    path: str | Path | None = None,
) -> dict[str, Any]:
    target = Path(path) if path is not None else default_vector_routes_fixture_path()
    if not target.is_file():
        raise VectorFixtureError(f"vector routes fixture missing: {target}")
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise VectorFixtureError(f"cannot load fixture: {target}") from exc
    if not isinstance(payload, Mapping):
        raise VectorFixtureError("vector routes fixture must be a mapping")
    if payload.get("schema_version") != FIXTURE_SCHEMA_VERSION:
        raise VectorFixtureError("vector routes fixture schema_version differs")
    if payload.get("task_id") != TASK_ID:
        raise VectorFixtureError("vector routes fixture task_id differs")
    return dict(payload)


def write_default_vector_routes_fixture(
    path: str | Path | None = None,
) -> Path:
    target = Path(path) if path is not None else default_vector_routes_fixture_path()
    payload = build_default_vector_routes_fixture_payload(include_realized=False)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return target


def binding_from_fixture(
    payload: Mapping[str, Any] | None = None,
    *,
    path: str | Path | None = None,
) -> UscodeVectorBinding:
    """Rebuild a :class:`UscodeVectorBinding` from the sealed fixture recipe."""

    data = (
        dict(payload)
        if payload is not None
        else load_vector_routes_fixture_payload(path)
    )
    chunks = data.get("chunks")
    if not isinstance(chunks, Sequence) or isinstance(chunks, (str, bytes)):
        raise VectorFixtureError("fixture chunks must be a sequence")
    bounds = data.get("test_bounds") or {}
    corpus_root = data.get("corpus_root_cid")
    return bind_uscode_vectors_from_chunks(
        list(chunks),
        corpus_root_cid=str(corpus_root) if corpus_root else None,
        seed=int(bounds.get("seed", DEFAULT_VECTOR_KMEANS_SEED)),
        max_rows_per_shard=int(bounds.get("max_rows_per_shard", 2)),
        max_shards_per_centroid=int(bounds.get("max_shards_per_centroid", 2)),
        max_rows_per_centroid=int(bounds.get("max_rows_per_centroid", 4)),
        target_rows_per_centroid=int(bounds.get("target_rows_per_centroid", 3)),
        kmeans_iterations=int(
            bounds.get("kmeans_iterations", DEFAULT_KMEANS_ITERATIONS)
        ),
        entry_locator_page_size=int(bounds.get("entry_locator_page_size", 4)),
    )


def run_vector_route_case(
    case: Mapping[str, Any],
    *,
    binding: UscodeVectorBinding | None = None,
    payload: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Execute one compact fixture case and return a structured result."""

    if not isinstance(case, Mapping):
        raise VectorFixtureError("case must be a mapping")
    case_id = str(case.get("case_id") or "unknown")
    kind = str(case.get("kind") or "")
    expect = case.get("expect") if isinstance(case.get("expect"), Mapping) else {}
    bound = binding or binding_from_fixture(payload)

    if kind == "coverage":
        keys = bound.vector_keys
        assert_every_chunk_once(bound.layout, expected_chunk_cids=keys)
        return {
            "case_id": case_id,
            "chunk_count": len(keys),
            "ok": True,
            "unique": len(keys) == len(set(keys)),
        }

    if kind == "bounds":
        assert_centroid_routes_bounded(bound.layout)
        for group in bound.layout.clusters:
            if group.row_count > int(expect.get("max_rows_per_centroid", 10**9)):
                raise VectorRouteBoundError("centroid row bound broken in case")
            if group.shard_count > int(
                expect.get("max_shards_per_centroid", 10**9)
            ):
                raise VectorRouteBoundError("centroid shard bound broken in case")
            for shard in group.shards:
                if shard.row_count > int(expect.get("max_rows_per_shard", 10**9)):
                    raise VectorRouteBoundError("shard row bound broken in case")
        return {
            "case_id": case_id,
            "cluster_count": bound.cluster_count,
            "ok": True,
            "shard_count": bound.shard_count,
        }

    if kind == "direct_cid":
        # Use the first vector as a query direction so ranking is defined.
        first_key = bound.vector_keys[0]
        # Reconstruct a unit query from the first shard row when available;
        # otherwise use a simple axis query.
        query = [1.0] + [0.0] * (bound.layout.dimension - 1)
        # Prefer an embedding from the layout for a realistic probe.
        for shard in bound.layout.shards:
            if shard.embeddings:
                query = list(shard.embeddings[0])
                break
        candidate_centroids = int(expect.get("candidate_centroids", 1))
        proof = prove_direct_cid_off_centroid_fetch(
            bound, query, candidate_centroids=candidate_centroids
        )
        minimum = int(expect.get("off_centroid_min", 1))
        if proof["off_centroid_count"] < minimum:
            raise VectorLocatorError(
                f"expected at least {minimum} off-centroid keys; "
                f"got {proof['off_centroid_count']}"
            )
        return {"case_id": case_id, "ok": True, **proof}

    if kind == "reconcile":
        result = reconcile_roots(
            bound,
            expected_model_id=bound.model_id,
            expected_model_revision=bound.model_revision,
            expected_config_cid=bound.config_cid,
            expected_vector_space_id=bound.vector_space_id,
            expected_corpus_root_cid=bound.corpus_root_cid,
            expected_layout_seed=bound.layout_seed,
            expected_vector_root_cid=bound.vector_root_cid,
        )
        return {"case_id": case_id, "ok": True, **result}

    if kind == "parent_links":
        expected_count = int(expect.get("parent_link_count", 0))
        if len(bound.parent_links) != expected_count:
            raise VectorBindingError(
                f"parent_link_count {len(bound.parent_links)} != {expected_count}"
            )
        for link in bound.parent_links:
            loc = bound.location_for(link.chunk_cid)
            if loc.entry_cid != link.entry_cid:
                raise VectorBindingError(
                    f"parent link drift for {link.chunk_cid!r}"
                )
        return {
            "case_id": case_id,
            "ok": True,
            "parent_link_count": len(bound.parent_links),
        }

    raise VectorFixtureError(f"unknown case kind: {kind!r}")


__all__ = [
    "ASSIGNMENT",
    "DEFAULT_CANDIDATE_CENTROIDS",
    "DEFAULT_VECTOR_KMEANS_SEED",
    "FIXTURE_SCHEMA_VERSION",
    "GOAL_ID",
    "MAX_ROWS_PER_PHYSICAL_SHARD",
    "MAX_ROWS_PER_VECTOR_CENTROID",
    "MAX_VECTOR_SHARDS_PER_CENTROID",
    "PARENT_KEY",
    "PRIMARY_KEY",
    "PRODUCER",
    "RELEASE_PROFILE",
    "ROWS_SORTED_BY",
    "SCHEMA_VERSION",
    "TASK_ID",
    "VECTOR_ENTRY_LOCATOR_DIR",
    "CorpusParentLink",
    "ManifestReadyDescriptor",
    "UscodeVectorBinding",
    "UscodeVectorError",
    "VectorBindingError",
    "VectorCoverageError",
    "VectorFixtureError",
    "VectorLocatorError",
    "VectorRootReconcileError",
    "VectorRouteBoundError",
    "VectorShardLocation",
    "assert_centroid_routes_bounded",
    "assert_every_chunk_once",
    "bind_uscode_vectors",
    "bind_uscode_vectors_from_chunks",
    "binding_from_fixture",
    "build_default_vector_routes_fixture_payload",
    "build_entry_locator_rows",
    "build_layout_root_cid",
    "build_location_map",
    "build_manifest_descriptors",
    "build_model_cid",
    "build_parent_links",
    "default_vector_routes_fixture_path",
    "embeddings_to_vector_records",
    "load_vector_routes_fixture_payload",
    "prove_direct_cid_off_centroid_fetch",
    "reconcile_roots",
    "run_vector_route_case",
    "select_off_centroid_keys",
    "write_default_vector_routes_fixture",
]
