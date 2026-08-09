"""Deterministic centroid-routed vector shards for HF GraphRAG (USCIR-018).

Domain-neutral clustering and physical layout for normalized embeddings:

* deterministic balanced spherical k-means with an explicit seed;
* recursive split of oversized groups so each centroid has at most
  8,192 rows and at most two physical shards;
* physical shards of at most 4,096 rows;
* rows sorted by descending cosine similarity to the shard centroid
  with a stable ``entry_cid`` tie-breaker;
* row conservation and uniqueness across the full layout; and
* compact routing metadata (normalized centroid, radius/score bounds,
  shard descriptors) suitable for thin-client centroid probing.

Domain builders (US Code, SkillCenter, CVEfixes) wrap these helpers;
this module owns no domain ontology or model-pin policy.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
import heapq
import math
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final

from .artifacts import (
    ArtifactWriterConfig,
    confine_path,
    describe_file,
    resolve_release_root,
    write_zstd_parquet,
)
from .schema import (
    DEFAULT_CANDIDATE_CENTROIDS,
    MAX_ROWS_PER_PHYSICAL_SHARD,
    MAX_ROWS_PER_VECTOR_CENTROID,
    MAX_VECTOR_SHARDS_PER_CENTROID,
    ArtifactFamily,
    HfGraphragSchemaError,
    PhysicalBoundError,
    canonical_json_dumps,
    content_sha256,
    normalize_relative_artifact_path,
    physical_bounds_policy,
    validate_physical_row_count,
)

# ---------------------------------------------------------------------------
# Module identity / defaults
# ---------------------------------------------------------------------------

VECTOR_LAYOUT_SCHEMA_VERSION: Final = "hf-graphrag-vector-layout/v1"
VECTOR_CHUNK_SCHEMA_VERSION: Final = "hf-graphrag-vector-chunk/v1"
VECTOR_ROUTING_SCHEMA_VERSION: Final = "hf-graphrag-vector-routing/v1"
VECTOR_FIXTURE_SCHEMA_VERSION: Final = "hf-graphrag-vector-clusters-fixture/v1"
TASK_ID: Final = "USCIR-018"
GOAL_ID: Final = "USCIR-G050"

# Explicit seed so the same multiset of unit vectors always yields the same
# partition.  Recorded in every layout receipt.
DEFAULT_VECTOR_KMEANS_SEED: Final = 0x55534349  # "USCI"
DEFAULT_KMEANS_ITERATIONS: Final = 6
DEFAULT_TARGET_ROWS_PER_CENTROID: Final = 2048
DEFAULT_MAX_CENTROIDS: Final = 65_536
DEFAULT_TRAINING_ROWS: Final = 65_536
NORM_TOLERANCE: Final = 2e-6
SCORE_TOLERANCE: Final = 2e-6
ASSIGNMENT: Final = "deterministic_balanced_spherical_kmeans"
ROWS_SORTED_BY: Final = "cosine_similarity_to_shard_centroid_desc"
VECTOR_DATA_DIR: Final = "data/vectors"
VECTOR_INDEX_PATH: Final = "indexes/vector_chunks.parquet"

VECTOR_DATA_COLUMNS: Final[tuple[str, ...]] = (
    "entry_cid",
    "cluster_id",
    "chunk_in_cluster",
    "document_index",
    "embedding",
    "schema_version",
)
VECTOR_META_COLUMNS: Final[tuple[str, ...]] = (
    "relative_path",
    "sha256",
    "size_bytes",
    "row_count",
    "shard_id",
    "first_key",
    "last_key",
    "kind",
    "schema_version",
    "content_cid",
    "centroid",
    "centroid_min_score",
    "centroid_max_score",
    "centroid_shard_count",
    "chunk_in_cluster",
    "cluster_id",
    "dimension",
    "shard_centroid",
)

# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class HfGraphragVectorError(HfGraphragSchemaError):
    """Base error for domain-neutral vector clustering / layout failures."""


class VectorInputError(HfGraphragVectorError):
    """Raised when input rows or embeddings are malformed."""


class VectorCoverageError(HfGraphragVectorError):
    """Raised when row conservation, uniqueness, or bounds fail."""


class VectorOrderingError(HfGraphragVectorError):
    """Raised when shard row ordering is not cosine-descending."""


class VectorRoutingError(HfGraphragVectorError):
    """Raised when centroid routing cannot complete safely."""


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class VectorRecord:
    """One normalized vector row keyed by durable ``entry_cid``."""

    entry_cid: str
    embedding: tuple[float, ...]
    document_index: int = 0
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.entry_cid, str) or not self.entry_cid.strip():
            raise VectorInputError("entry_cid must be a non-empty string")
        object.__setattr__(self, "entry_cid", self.entry_cid.strip())
        if (
            not isinstance(self.document_index, int)
            or isinstance(self.document_index, bool)
            or self.document_index < 0
        ):
            raise VectorInputError("document_index must be a non-negative integer")
        if not isinstance(self.embedding, Sequence) or isinstance(
            self.embedding, (str, bytes, bytearray)
        ):
            raise VectorInputError("embedding must be a sequence of floats")
        values = tuple(float(value) for value in self.embedding)
        if not values:
            raise VectorInputError("embedding must be non-empty")
        if any(not math.isfinite(value) for value in values):
            raise VectorInputError(
                f"embedding for {self.entry_cid!r} contains non-finite values"
            )
        object.__setattr__(self, "embedding", values)
        if not isinstance(self.metadata, Mapping):
            raise VectorInputError("metadata must be a mapping")
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "document_index": self.document_index,
            "embedding": list(self.embedding),
            "entry_cid": self.entry_cid,
        }
        if self.metadata:
            payload["metadata"] = dict(self.metadata)
        return payload


@dataclass(frozen=True, slots=True)
class VectorShardSpec:
    """One physical vector shard within a centroid group."""

    cluster_id: int
    chunk_in_cluster: int
    global_shard_id: int
    entry_cids: tuple[str, ...]
    document_indexes: tuple[int, ...]
    embeddings: tuple[tuple[float, ...], ...]
    scores: tuple[float, ...]
    routing_centroid: tuple[float, ...]
    shard_centroid: tuple[float, ...]
    min_score: float
    max_score: float
    relative_path: str
    dimension: int

    @property
    def row_count(self) -> int:
        return len(self.entry_cids)

    @property
    def centroid_shard_count_hint(self) -> int:
        # Filled at layout level; kept for single-shard convenience.
        return 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "chunk_in_cluster": self.chunk_in_cluster,
            "cluster_id": self.cluster_id,
            "dimension": self.dimension,
            "document_indexes": list(self.document_indexes),
            "embeddings": [list(vector) for vector in self.embeddings],
            "entry_cids": list(self.entry_cids),
            "global_shard_id": self.global_shard_id,
            "max_score": self.max_score,
            "min_score": self.min_score,
            "relative_path": self.relative_path,
            "routing_centroid": list(self.routing_centroid),
            "row_count": self.row_count,
            "scores": list(self.scores),
            "shard_centroid": list(self.shard_centroid),
        }

    def routing_row(
        self,
        *,
        centroid_shard_count: int,
        sha256: str = "",
        size_bytes: int = 0,
        content_cid: str | None = None,
    ) -> dict[str, Any]:
        """Compact routing-index row for this shard (descriptor fields optional)."""

        payload: dict[str, Any] = {
            "centroid": list(self.routing_centroid),
            "centroid_max_score": float(self.max_score),
            "centroid_min_score": float(self.min_score),
            "centroid_shard_count": int(centroid_shard_count),
            "chunk_in_cluster": int(self.chunk_in_cluster),
            "cluster_id": int(self.cluster_id),
            "dimension": int(self.dimension),
            "first_key": self.entry_cids[0] if self.entry_cids else "",
            "kind": ArtifactFamily.VECTORS.value,
            "last_key": self.entry_cids[-1] if self.entry_cids else "",
            "relative_path": self.relative_path,
            "row_count": self.row_count,
            "schema_version": VECTOR_ROUTING_SCHEMA_VERSION,
            "sha256": sha256,
            "shard_centroid": list(self.shard_centroid),
            "shard_id": int(self.global_shard_id),
            "size_bytes": int(size_bytes),
        }
        if content_cid is not None:
            payload["content_cid"] = content_cid
            payload["cid"] = content_cid
        return payload


@dataclass(frozen=True, slots=True)
class VectorClusterGroup:
    """One semantic centroid group and its physical shards."""

    cluster_id: int
    entry_cids: tuple[str, ...]
    routing_centroid: tuple[float, ...]
    shards: tuple[VectorShardSpec, ...]

    @property
    def row_count(self) -> int:
        return len(self.entry_cids)

    @property
    def shard_count(self) -> int:
        return len(self.shards)

    def to_dict(self) -> dict[str, Any]:
        return {
            "cluster_id": self.cluster_id,
            "entry_cids": list(self.entry_cids),
            "routing_centroid": list(self.routing_centroid),
            "row_count": self.row_count,
            "shard_count": self.shard_count,
            "shards": [shard.to_dict() for shard in self.shards],
        }


@dataclass(frozen=True, slots=True)
class VectorClusterLayout:
    """Complete centroid-routed layout for a multiset of unit vectors."""

    clusters: tuple[VectorClusterGroup, ...]
    dimension: int
    total_rows: int
    seed: int
    max_rows_per_shard: int
    max_rows_per_centroid: int
    max_shards_per_centroid: int
    target_rows_per_centroid: int
    kmeans_iterations: int
    assignment: str = ASSIGNMENT
    schema_version: str = VECTOR_LAYOUT_SCHEMA_VERSION

    @property
    def cluster_count(self) -> int:
        return len(self.clusters)

    @property
    def shard_count(self) -> int:
        return sum(group.shard_count for group in self.clusters)

    @property
    def shards(self) -> tuple[VectorShardSpec, ...]:
        return tuple(
            shard for group in self.clusters for shard in group.shards
        )

    def all_entry_cids(self) -> tuple[str, ...]:
        return tuple(
            entry_cid
            for group in self.clusters
            for entry_cid in group.entry_cids
        )

    def routing_rows(
        self,
        *,
        descriptors: Mapping[str, Mapping[str, Any]] | None = None,
    ) -> tuple[dict[str, Any], ...]:
        """Emit ordered compact routing rows for every physical shard."""

        descriptor_map = descriptors or {}
        rows: list[dict[str, Any]] = []
        for group in self.clusters:
            for shard in group.shards:
                extra = descriptor_map.get(shard.relative_path, {})
                rows.append(
                    shard.routing_row(
                        centroid_shard_count=group.shard_count,
                        sha256=str(extra.get("sha256", "")),
                        size_bytes=int(extra.get("size_bytes", 0) or 0),
                        content_cid=extra.get("content_cid") or extra.get("cid"),
                    )
                )
        return tuple(rows)

    def to_dict(self) -> dict[str, Any]:
        return {
            "assignment": self.assignment,
            "cluster_count": self.cluster_count,
            "clusters": [group.to_dict() for group in self.clusters],
            "dimension": self.dimension,
            "kmeans_iterations": self.kmeans_iterations,
            "max_rows_per_centroid": self.max_rows_per_centroid,
            "max_rows_per_shard": self.max_rows_per_shard,
            "max_shards_per_centroid": self.max_shards_per_centroid,
            "rows_sorted_by": ROWS_SORTED_BY,
            "schema_version": self.schema_version,
            "seed": self.seed,
            "shard_count": self.shard_count,
            "similarity": "cosine",
            "target_rows_per_centroid": self.target_rows_per_centroid,
            "total_rows": self.total_rows,
        }

    def manifest_config(self) -> dict[str, Any]:
        """Compact layout config for release manifests / receipts."""

        return {
            "assignment": self.assignment,
            "centroid_count": self.cluster_count,
            "default_probe_centroids": min(
                DEFAULT_CANDIDATE_CENTROIDS, max(self.cluster_count, 0)
            ),
            "dimension": self.dimension,
            "kmeans_iterations": self.kmeans_iterations,
            "layout": "semantic_centroid_groups",
            "max_rows_per_centroid": self.max_rows_per_centroid,
            "max_rows_per_chunk": self.max_rows_per_shard,
            "max_shards_per_centroid": self.max_shards_per_centroid,
            "rows_sorted_by": ROWS_SORTED_BY,
            "schema_version": self.schema_version,
            "seed": self.seed,
            "shard_count": self.shard_count,
            "similarity": "cosine",
            "target_rows_per_centroid": self.target_rows_per_centroid,
            "total_rows": self.total_rows,
        }


@dataclass(frozen=True, slots=True)
class VectorLayoutWriteResult:
    """On-disk write outcome for a centroid-routed vector layout."""

    layout: VectorClusterLayout
    data_descriptors: tuple[Any, ...]
    routing_rows: tuple[dict[str, Any], ...]
    routing_index_descriptor: Any | None
    output_root: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "data_descriptors": [
                item.to_dict() if hasattr(item, "to_dict") else dict(item)
                for item in self.data_descriptors
            ],
            "layout": self.layout.to_dict(),
            "output_root": self.output_root,
            "routing_index": (
                self.routing_index_descriptor.to_dict()
                if self.routing_index_descriptor is not None
                and hasattr(self.routing_index_descriptor, "to_dict")
                else self.routing_index_descriptor
            ),
            "routing_rows": [dict(row) for row in self.routing_rows],
        }


@dataclass(frozen=True, slots=True)
class VectorShardRoute:
    """One verified routing decision for a thin remote client."""

    cluster_id: int
    chunk_in_cluster: int
    score: float
    relative_path: str
    row_count: int
    shard_id: int
    sha256: str = ""
    size_bytes: int = 0
    content_cid: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "chunk_in_cluster": self.chunk_in_cluster,
            "cluster_id": self.cluster_id,
            "relative_path": self.relative_path,
            "row_count": self.row_count,
            "score": self.score,
            "shard_id": self.shard_id,
            "sha256": self.sha256,
            "size_bytes": self.size_bytes,
        }
        if self.content_cid is not None:
            payload["content_cid"] = self.content_cid
            payload["cid"] = self.content_cid
        return payload


# ---------------------------------------------------------------------------
# Public configuration helpers
# ---------------------------------------------------------------------------


def vector_bounds_policy() -> dict[str, int]:
    """Return sealed vector physical bounds (subset of shared policy)."""

    bounds = physical_bounds_policy()
    return {
        "default_candidate_centroids": DEFAULT_CANDIDATE_CENTROIDS,
        "max_rows_per_physical_shard": bounds["max_rows_per_physical_shard"],
        "max_rows_per_vector_centroid": bounds["max_rows_per_vector_centroid"],
        "max_vector_shards_per_centroid": bounds["max_vector_shards_per_centroid"],
    }


def centroid_part_filename(
    cluster_id: int,
    chunk_in_cluster: int,
    *,
    width: int = 6,
) -> str:
    """Return ``centroid-NNNNNN-part-MMMMMM.parquet`` for a physical shard."""

    if (
        not isinstance(cluster_id, int)
        or isinstance(cluster_id, bool)
        or cluster_id < 0
    ):
        raise VectorInputError("cluster_id must be a non-negative integer")
    if (
        not isinstance(chunk_in_cluster, int)
        or isinstance(chunk_in_cluster, bool)
        or chunk_in_cluster < 0
    ):
        raise VectorInputError("chunk_in_cluster must be a non-negative integer")
    if width < 1:
        raise VectorInputError("width must be a positive integer")
    return (
        f"centroid-{cluster_id:0{width}d}-part-{chunk_in_cluster:0{width}d}.parquet"
    )


def vector_shard_relative_path(
    cluster_id: int,
    chunk_in_cluster: int,
    *,
    data_dir: str = VECTOR_DATA_DIR,
    width: int = 6,
) -> str:
    """Release-relative path for one centroid-local physical shard."""

    directory = normalize_relative_artifact_path(data_dir)
    name = centroid_part_filename(
        cluster_id, chunk_in_cluster, width=width
    )
    return f"{directory}/{name}"


# ---------------------------------------------------------------------------
# Input coercion / normalization
# ---------------------------------------------------------------------------


def _positive_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise VectorInputError(f"{name} must be a positive integer")
    return value


def _non_negative_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise VectorInputError(f"{name} must be a non-negative integer")
    return value


def _numpy() -> Any:
    try:
        import numpy as np
    except ImportError as exc:  # pragma: no cover - optional dependency guard
        raise HfGraphragVectorError(
            "numpy is required for centroid-routed vector clustering"
        ) from exc
    return np


def coerce_vector_records(
    rows: Sequence[Mapping[str, Any] | VectorRecord],
) -> tuple[VectorRecord, ...]:
    """Coerce mappings / records into validated :class:`VectorRecord` values."""

    if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes, bytearray)):
        raise VectorInputError("rows must be a sequence of vector records")
    records: list[VectorRecord] = []
    for position, row in enumerate(rows):
        if isinstance(row, VectorRecord):
            records.append(row)
            continue
        if not isinstance(row, Mapping):
            raise VectorInputError(f"rows[{position}] must be a mapping")
        entry_cid = row.get("entry_cid") or row.get("chunk_cid") or row.get("cid")
        embedding = row.get("embedding")
        if embedding is None:
            embedding = row.get("vector")
        document_index = row.get("document_index", position)
        metadata = {
            key: value
            for key, value in row.items()
            if key
            not in {
                "entry_cid",
                "chunk_cid",
                "cid",
                "embedding",
                "vector",
                "document_index",
            }
        }
        records.append(
            VectorRecord(
                entry_cid=str(entry_cid or ""),
                embedding=tuple(embedding or ()),
                document_index=int(document_index),
                metadata=metadata,
            )
        )
    return tuple(records)


def normalize_unit_matrix(
    records: Sequence[VectorRecord],
    *,
    np: Any | None = None,
    tolerance: float = NORM_TOLERANCE,
) -> Any:
    """Return an ``(n, d)`` float32 matrix of L2-normalized embeddings."""

    if not records:
        raise VectorInputError("cannot cluster an empty vector set")
    numpy = np if np is not None else _numpy()
    dimension = len(records[0].embedding)
    if dimension < 1:
        raise VectorInputError("embedding dimension must be positive")
    matrix = numpy.zeros((len(records), dimension), dtype=numpy.float32)
    seen: set[str] = set()
    for position, record in enumerate(records):
        if record.entry_cid in seen:
            raise VectorCoverageError(
                f"duplicate entry_cid in vector input: {record.entry_cid!r}"
            )
        seen.add(record.entry_cid)
        if len(record.embedding) != dimension:
            raise VectorInputError(
                f"embedding dimension mismatch for {record.entry_cid!r}: "
                f"expected {dimension}, got {len(record.embedding)}"
            )
        vector = numpy.asarray(record.embedding, dtype=numpy.float64)
        if vector.shape != (dimension,) or not numpy.isfinite(vector).all():
            raise VectorInputError(
                f"embedding for {record.entry_cid!r} is malformed"
            )
        norm = float(numpy.linalg.norm(vector))
        if not math.isfinite(norm) or norm == 0.0:
            raise VectorInputError(
                f"embedding for {record.entry_cid!r} must be finite and non-zero"
            )
        unit = (vector / norm).astype(numpy.float32)
        unit_norm = float(numpy.linalg.norm(unit))
        if not math.isfinite(unit_norm) or unit_norm == 0.0:
            raise VectorInputError(
                f"embedding for {record.entry_cid!r} cannot be normalized"
            )
        unit = unit / unit_norm
        # Accept already-normalized inputs within tolerance; re-normalize always.
        if abs(float(numpy.linalg.norm(unit)) - 1.0) > tolerance:
            raise VectorInputError(
                f"embedding for {record.entry_cid!r} failed unit-norm check"
            )
        matrix[position] = unit.astype(numpy.float32)
    return matrix


# ---------------------------------------------------------------------------
# Balanced spherical k-means primitives
# ---------------------------------------------------------------------------


def _balanced_capacities(row_count: int, group_count: int) -> list[int]:
    if group_count < 1 or group_count > row_count:
        raise VectorInputError("balanced group count is malformed")
    base, remainder = divmod(row_count, group_count)
    return [
        base + (1 if group_id < remainder else 0)
        for group_id in range(group_count)
    ]


def _balanced_position_groups(
    positions: Sequence[int],
    group_count: int,
) -> list[list[int]]:
    capacities = _balanced_capacities(len(positions), group_count)
    groups: list[list[int]] = []
    offset = 0
    for capacity in capacities:
        groups.append(
            [int(value) for value in positions[offset : offset + capacity]]
        )
        offset += capacity
    return groups


def _unit_centroid(matrix: Any, positions: Any, *, np: Any) -> Any:
    selected = matrix[positions]
    if len(selected) == 0:
        return np.zeros(matrix.shape[1], dtype=np.float32)
    centroid = selected.astype(np.float64).mean(axis=0)
    norm = float(np.linalg.norm(centroid))
    if not math.isfinite(norm) or norm == 0.0:
        # Opposing vectors can cancel.  Lowest matrix index is a deterministic
        # member-vector fallback.
        fallback_index = int(np.min(np.asarray(positions, dtype=np.int64)))
        centroid = matrix[fallback_index].astype(np.float64)
        norm = float(np.linalg.norm(centroid))
        if not math.isfinite(norm) or norm == 0.0:
            return np.zeros(matrix.shape[1], dtype=np.float32)
    result = (centroid / norm).astype(np.float32)
    result_norm = float(np.linalg.norm(result))
    if not math.isfinite(result_norm) or result_norm == 0.0:
        return np.zeros(matrix.shape[1], dtype=np.float32)
    return (result / result_norm).astype(np.float32)


def _seeded_training_positions(
    positions: Any,
    *,
    seed: int,
    max_training_rows: int,
    np: Any,
) -> Any:
    """Deterministically sample training rows under *seed*."""

    count = int(len(positions))
    if count <= max_training_rows:
        return positions
    rng = np.random.default_rng(int(seed) & 0x7FFFFFFF)
    # Sort then sample without replacement so input order alone cannot bias
    # the training multiset; the seed fully determines the subset.
    ordered = np.sort(np.asarray(positions, dtype=np.int64))
    chosen = rng.choice(ordered, size=max_training_rows, replace=False)
    return np.sort(chosen)


def _learn_centroids(
    matrix: Any,
    positions: Any,
    cluster_count: int,
    *,
    iterations: int,
    seed: int,
    max_training_rows: int,
    np: Any,
) -> Any:
    """Learn unit spherical centroids via seeded farthest-point + refinement."""

    if cluster_count < 1 or cluster_count > len(positions):
        raise VectorInputError("semantic centroid count is malformed")
    training_positions = _seeded_training_positions(
        positions,
        seed=seed,
        max_training_rows=max_training_rows,
        np=np,
    )
    training = matrix[training_positions]
    # Seeded first pick among training rows (stable for a given seed).
    rng = np.random.default_rng((int(seed) ^ (cluster_count * 0x9E3779B1)) & 0x7FFFFFFF)
    first = int(rng.integers(0, len(training_positions)))
    selected: list[int] = [first]
    while len(selected) < cluster_count:
        centroids = training[np.asarray(selected, dtype=np.int64)]
        nearest = (training @ centroids.T).max(axis=1)
        nearest[np.asarray(selected, dtype=np.int64)] = np.inf
        # Among equidistant candidates, break ties by seeded hash of index so
        # the same seed always picks the same next centroid.
        min_value = float(nearest.min())
        candidates = np.flatnonzero(np.isclose(nearest, min_value, atol=1e-12))
        if len(candidates) == 1:
            selected.append(int(candidates[0]))
        else:
            # Deterministic pseudo-random order over candidate local indices.
            scores = [
                (
                    (
                        int(seed)
                        + 0xA5A5A5A5
                        + int(local) * 0x9E3779B97F4A7C15
                    )
                    & 0xFFFFFFFFFFFFFFFF,
                    int(local),
                )
                for local in candidates
            ]
            scores.sort()
            selected.append(scores[0][1])
    centroids = training[np.asarray(selected, dtype=np.int64)].copy()
    work_positions = training_positions
    work_matrix = training
    for _ in range(iterations):
        assignments = np.argmax(work_matrix @ centroids.T, axis=1)
        updated = centroids.copy()
        for cluster_id in range(cluster_count):
            members = work_positions[np.flatnonzero(assignments == cluster_id)]
            if not len(members):
                continue
            candidate = _unit_centroid(matrix, members, np=np)
            if float(np.linalg.norm(candidate)) == 0.0:
                candidate = matrix[int(np.min(members))]
            updated[cluster_id] = candidate
        if np.allclose(updated, centroids, atol=1e-7, rtol=0.0):
            centroids = updated
            break
        centroids = updated
    return centroids.astype(np.float32)


def _capacity_constrained_assignments(scores: Any, *, np: Any) -> Any:
    """Stable nearest-centroid assignment with exact balanced capacities."""

    values = np.asarray(scores, dtype=np.float32)
    if (
        values.ndim != 2
        or values.shape[0] < 1
        or values.shape[1] < 1
        or not np.isfinite(values).all()
    ):
        raise VectorInputError("centroid score matrix is malformed")
    row_count, cluster_count = values.shape
    capacities = _balanced_capacities(row_count, cluster_count)
    preferences = np.argsort(-values, axis=1, kind="stable")
    next_preference = np.zeros(row_count, dtype=np.int32)
    assignments = np.full(row_count, -1, dtype=np.int32)
    accepted: list[list[tuple[float, int, int]]] = [[] for _ in range(cluster_count)]
    pending = deque(range(row_count))
    while pending:
        row_id = int(pending.popleft())
        rank = int(next_preference[row_id])
        if rank >= cluster_count:
            raise VectorCoverageError(
                "capacity-constrained assignment did not converge"
            )
        cluster_id = int(preferences[row_id, rank])
        next_preference[row_id] = rank + 1
        proposal = (
            float(values[row_id, cluster_id]),
            -row_id,
            row_id,
        )
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
    if (
        bool((assignments < 0).any())
        or list(np.bincount(assignments, minlength=cluster_count)) != capacities
    ):
        raise VectorCoverageError(
            "balanced centroid assignment coverage differs"
        )
    return assignments


def _spherical_kmeans_groups(
    matrix: Any,
    positions: Sequence[int] | Any,
    cluster_count: int,
    *,
    seed: int,
    iterations: int,
    max_training_rows: int,
    np: Any,
) -> list[list[int]]:
    """Partition *positions* into *cluster_count* balanced spherical groups."""

    position_array = np.asarray(list(positions), dtype=np.int64)
    row_count = int(len(position_array))
    if row_count < 1:
        return []
    cluster_count = min(int(cluster_count), row_count)
    if cluster_count < 1:
        raise VectorInputError("spherical vector cluster count must be positive")
    if cluster_count == 1:
        return [[int(value) for value in position_array]]
    centroids = _learn_centroids(
        matrix,
        position_array,
        cluster_count,
        iterations=iterations,
        seed=seed,
        max_training_rows=max_training_rows,
        np=np,
    )
    assignments = _capacity_constrained_assignments(
        matrix[position_array] @ centroids.T,
        np=np,
    )
    groups = [
        [
            int(value)
            for value in position_array[np.flatnonzero(assignments == cluster_id)]
        ]
        for cluster_id in range(cluster_count)
    ]
    return [group for group in groups if group]


def _recursive_bounded_groups(
    matrix: Any,
    positions: Sequence[int] | Any,
    *,
    max_rows_per_centroid: int,
    target_rows_per_centroid: int,
    seed: int,
    iterations: int,
    max_training_rows: int,
    max_centroids: int,
    np: Any,
    depth: int = 0,
) -> list[list[int]]:
    """Recursively partition so every group fits the centroid row bound."""

    position_list = [int(value) for value in positions]
    row_count = len(position_list)
    if row_count == 0:
        return []
    if row_count <= max_rows_per_centroid:
        # Still allow target-driven splits when the group is large enough to
        # benefit from more routing centroids, but never exceed max_centroids.
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
            np=np,
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
                    np=np,
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
        np=np,
    )
    if len(children) < 2 or max(map(len, children)) == row_count:
        # Hard geometric fallback: stable index slices of max size.
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
                np=np,
                depth=depth + 1,
            )
        )
    return output


def _physical_shards(
    matrix: Any,
    positions: Sequence[int] | Any,
    *,
    max_rows_per_shard: int,
    max_shards_per_centroid: int,
    seed: int,
    iterations: int,
    max_training_rows: int,
    np: Any,
) -> list[list[int]]:
    """Split one centroid group into 1..max_shards balanced physical shards."""

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
        np=np,
    )
    if len(children) != shard_count:
        return _balanced_position_groups(position_list, shard_count)
    # Re-order shards by lowest entry position for deterministic global order.
    children = sorted(children, key=lambda group: (min(group), len(group), group[0]))
    return children


def _sort_shard_offsets(
    matrix: Any,
    positions: Sequence[int],
    shard_centroid: Any,
    *,
    entry_cids: Sequence[str],
    np: Any,
) -> tuple[list[int], list[float]]:
    """Return positions ordered by cosine desc, then entry_cid asc."""

    position_array = np.asarray(list(positions), dtype=np.int64)
    scores = matrix[position_array] @ shard_centroid
    ordered = sorted(
        range(len(position_array)),
        key=lambda offset: (
            -float(scores[offset]),
            entry_cids[int(position_array[offset])],
            int(position_array[offset]),
        ),
    )
    ordered_positions = [int(position_array[offset]) for offset in ordered]
    ordered_scores = [float(scores[offset]) for offset in ordered]
    return ordered_positions, ordered_scores


# ---------------------------------------------------------------------------
# Layout construction
# ---------------------------------------------------------------------------


def build_centroid_routed_vector_layout(
    rows: Sequence[Mapping[str, Any] | VectorRecord],
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
    """Cluster normalized vectors into bounded centroid-routed shards.

    Guarantees:

    * every input ``entry_cid`` appears in exactly one shard (conservation);
    * each centroid group has ``<= max_rows_per_centroid`` rows and
      ``<= max_shards_per_centroid`` physical shards;
    * each physical shard has ``<= max_rows_per_shard`` rows;
    * rows inside a shard are sorted by descending cosine to the shard
      centroid with ``entry_cid`` as the stable tie-breaker;
    * the same multiset of rows and the same *seed* always produce the same
      layout (ordering of input rows does not affect the result).
    """

    max_rows_per_shard = _positive_int(max_rows_per_shard, "max_rows_per_shard")
    max_shards_per_centroid = _positive_int(
        max_shards_per_centroid, "max_shards_per_centroid"
    )
    target_rows_per_centroid = _positive_int(
        target_rows_per_centroid, "target_rows_per_centroid"
    )
    max_centroids = _positive_int(max_centroids, "max_centroids")
    kmeans_iterations = _positive_int(kmeans_iterations, "kmeans_iterations")
    max_training_rows = _positive_int(max_training_rows, "max_training_rows")
    seed = _non_negative_int(seed, "seed")

    if max_rows_per_shard > MAX_ROWS_PER_PHYSICAL_SHARD:
        raise PhysicalBoundError(
            f"max_rows_per_shard={max_rows_per_shard} exceeds "
            f"{MAX_ROWS_PER_PHYSICAL_SHARD}"
        )
    if max_shards_per_centroid > MAX_VECTOR_SHARDS_PER_CENTROID:
        raise PhysicalBoundError(
            f"max_shards_per_centroid={max_shards_per_centroid} exceeds "
            f"{MAX_VECTOR_SHARDS_PER_CENTROID}"
        )
    if max_rows_per_centroid is None:
        max_rows_per_centroid = max_rows_per_shard * max_shards_per_centroid
    max_rows_per_centroid = _positive_int(
        max_rows_per_centroid, "max_rows_per_centroid"
    )
    if max_rows_per_centroid > MAX_ROWS_PER_VECTOR_CENTROID:
        raise PhysicalBoundError(
            f"max_rows_per_centroid={max_rows_per_centroid} exceeds "
            f"{MAX_ROWS_PER_VECTOR_CENTROID}"
        )
    if max_rows_per_centroid > max_rows_per_shard * max_shards_per_centroid:
        raise PhysicalBoundError(
            "max_rows_per_centroid exceeds shard capacity "
            f"({max_rows_per_shard} * {max_shards_per_centroid})"
        )
    if target_rows_per_centroid > max_rows_per_centroid:
        raise VectorInputError(
            "target_rows_per_centroid exceeds max_rows_per_centroid"
        )

    records = coerce_vector_records(rows)
    # Canonical input order: sort by entry_cid so input permutation is irrelevant.
    ordered_records = tuple(
        sorted(records, key=lambda item: (item.entry_cid, item.document_index))
    )
    np = _numpy()
    matrix = normalize_unit_matrix(ordered_records, np=np)
    dimension = int(matrix.shape[1])
    entry_cids = tuple(record.entry_cid for record in ordered_records)
    document_indexes = tuple(record.document_index for record in ordered_records)

    groups = _recursive_bounded_groups(
        matrix,
        list(range(len(ordered_records))),
        max_rows_per_centroid=max_rows_per_centroid,
        target_rows_per_centroid=target_rows_per_centroid,
        seed=seed,
        iterations=kmeans_iterations,
        max_training_rows=max_training_rows,
        max_centroids=max_centroids,
        np=np,
    )
    if not groups:
        raise VectorCoverageError("vector centroid coverage is empty")

    # Stable cluster ordering: by lowest entry_cid, then size, then first index.
    groups = sorted(
        groups,
        key=lambda group: (
            min(entry_cids[index] for index in group),
            len(group),
            min(group),
        ),
    )

    cluster_groups: list[VectorClusterGroup] = []
    global_shard_id = 0
    for cluster_id, group_positions in enumerate(groups):
        if len(group_positions) > max_rows_per_centroid:
            raise VectorCoverageError(
                f"cluster {cluster_id} has {len(group_positions)} rows; "
                f"exceeds {max_rows_per_centroid}"
            )
        routing_centroid = _unit_centroid(matrix, group_positions, np=np)
        physical = _physical_shards(
            matrix,
            group_positions,
            max_rows_per_shard=max_rows_per_shard,
            max_shards_per_centroid=max_shards_per_centroid,
            seed=seed + 1_000_000 + cluster_id * 97,
            iterations=kmeans_iterations,
            max_training_rows=max_training_rows,
            np=np,
        )
        if not 1 <= len(physical) <= max_shards_per_centroid:
            raise VectorCoverageError(
                f"cluster {cluster_id} produced {len(physical)} shards; "
                f"expected 1..{max_shards_per_centroid}"
            )
        shard_specs: list[VectorShardSpec] = []
        for chunk_in_cluster, selected in enumerate(physical):
            if len(selected) > max_rows_per_shard:
                raise VectorCoverageError(
                    f"shard cluster={cluster_id} chunk={chunk_in_cluster} "
                    f"has {len(selected)} rows; exceeds {max_rows_per_shard}"
                )
            validate_physical_row_count(
                len(selected), maximum=max_rows_per_shard
            )
            shard_centroid = _unit_centroid(matrix, selected, np=np)
            ordered_positions, ordered_scores = _sort_shard_offsets(
                matrix,
                selected,
                shard_centroid,
                entry_cids=entry_cids,
                np=np,
            )
            relative_path = vector_shard_relative_path(
                cluster_id,
                chunk_in_cluster,
                data_dir=data_dir,
            )
            shard_specs.append(
                VectorShardSpec(
                    cluster_id=cluster_id,
                    chunk_in_cluster=chunk_in_cluster,
                    global_shard_id=global_shard_id,
                    entry_cids=tuple(entry_cids[index] for index in ordered_positions),
                    document_indexes=tuple(
                        document_indexes[index] for index in ordered_positions
                    ),
                    embeddings=tuple(
                        tuple(float(value) for value in matrix[index].tolist())
                        for index in ordered_positions
                    ),
                    scores=tuple(ordered_scores),
                    routing_centroid=tuple(
                        float(value) for value in routing_centroid.tolist()
                    ),
                    shard_centroid=tuple(
                        float(value) for value in shard_centroid.tolist()
                    ),
                    min_score=float(min(ordered_scores)) if ordered_scores else 0.0,
                    max_score=float(max(ordered_scores)) if ordered_scores else 0.0,
                    relative_path=relative_path,
                    dimension=dimension,
                )
            )
            global_shard_id += 1
        cluster_entry_cids = tuple(
            entry_cid
            for shard in shard_specs
            for entry_cid in shard.entry_cids
        )
        cluster_groups.append(
            VectorClusterGroup(
                cluster_id=cluster_id,
                entry_cids=cluster_entry_cids,
                routing_centroid=tuple(
                    float(value) for value in routing_centroid.tolist()
                ),
                shards=tuple(shard_specs),
            )
        )

    layout = VectorClusterLayout(
        clusters=tuple(cluster_groups),
        dimension=dimension,
        total_rows=len(ordered_records),
        seed=seed,
        max_rows_per_shard=max_rows_per_shard,
        max_rows_per_centroid=max_rows_per_centroid,
        max_shards_per_centroid=max_shards_per_centroid,
        target_rows_per_centroid=target_rows_per_centroid,
        kmeans_iterations=kmeans_iterations,
    )
    validate_vector_layout(layout, expected_entry_cids=entry_cids)
    return layout


def validate_vector_layout(
    layout: VectorClusterLayout,
    *,
    expected_entry_cids: Sequence[str] | None = None,
) -> None:
    """Fail closed if conservation, uniqueness, bounds, or ordering break."""

    if not isinstance(layout, VectorClusterLayout):
        raise VectorCoverageError("layout must be a VectorClusterLayout")
    observed: list[str] = []
    for group in layout.clusters:
        if group.row_count > layout.max_rows_per_centroid:
            raise VectorCoverageError(
                f"cluster {group.cluster_id} exceeds max_rows_per_centroid"
            )
        if group.shard_count > layout.max_shards_per_centroid:
            raise VectorCoverageError(
                f"cluster {group.cluster_id} exceeds max_shards_per_centroid"
            )
        if group.shard_count < 1:
            raise VectorCoverageError(
                f"cluster {group.cluster_id} has no physical shards"
            )
        if sum(shard.row_count for shard in group.shards) != group.row_count:
            raise VectorCoverageError(
                f"cluster {group.cluster_id} shard row sum differs"
            )
        for shard in group.shards:
            if shard.row_count > layout.max_rows_per_shard:
                raise VectorCoverageError(
                    f"shard {shard.relative_path} exceeds max_rows_per_shard"
                )
            if shard.row_count != len(shard.entry_cids):
                raise VectorCoverageError(
                    f"shard {shard.relative_path} entry_cid count differs"
                )
            if len(shard.entry_cids) != len(set(shard.entry_cids)):
                raise VectorCoverageError(
                    f"shard {shard.relative_path} has duplicate entry_cids"
                )
            if len(shard.scores) != shard.row_count:
                raise VectorCoverageError(
                    f"shard {shard.relative_path} score count differs"
                )
            # Ordering: scores non-increasing; ties broken by entry_cid.
            for offset in range(1, shard.row_count):
                previous = (
                    -shard.scores[offset - 1],
                    shard.entry_cids[offset - 1],
                )
                current = (
                    -shard.scores[offset],
                    shard.entry_cids[offset],
                )
                if current < previous:
                    raise VectorOrderingError(
                        f"shard {shard.relative_path} is not cosine-sorted"
                    )
            # Score bounds.
            if shard.row_count:
                if not math.isclose(
                    shard.min_score,
                    min(shard.scores),
                    abs_tol=SCORE_TOLERANCE,
                    rel_tol=0.0,
                ) or not math.isclose(
                    shard.max_score,
                    max(shard.scores),
                    abs_tol=SCORE_TOLERANCE,
                    rel_tol=0.0,
                ):
                    raise VectorCoverageError(
                        f"shard {shard.relative_path} score bounds differ"
                    )
            # Unit-norm checks on centroids.
            for label, vector in (
                ("routing_centroid", shard.routing_centroid),
                ("shard_centroid", shard.shard_centroid),
            ):
                norm = math.sqrt(sum(value * value for value in vector))
                if not math.isclose(norm, 1.0, abs_tol=NORM_TOLERANCE, rel_tol=0.0):
                    raise VectorCoverageError(
                        f"shard {shard.relative_path} {label} is not unit length"
                    )
            observed.extend(shard.entry_cids)

    if len(observed) != layout.total_rows:
        raise VectorCoverageError(
            f"layout total_rows={layout.total_rows} but observed {len(observed)}"
        )
    if len(observed) != len(set(observed)):
        raise VectorCoverageError("layout contains duplicate entry_cids")
    if expected_entry_cids is not None:
        expected = list(expected_entry_cids)
        if sorted(observed) != sorted(expected):
            raise VectorCoverageError(
                "layout entry_cid set differs from expected input set"
            )
        if len(expected) != len(set(expected)):
            raise VectorCoverageError("expected entry_cids are not unique")


# ---------------------------------------------------------------------------
# Routing
# ---------------------------------------------------------------------------


def route_vector_shards(
    routing_rows: Sequence[Mapping[str, Any]],
    query_embedding: Sequence[float],
    *,
    candidate_centroids: int = DEFAULT_CANDIDATE_CENTROIDS,
    max_shards: int | None = None,
) -> tuple[VectorShardRoute, ...]:
    """Rank routing centroids and return the selected physical shard routes.

    Does not open any data shard.  Only the compact routing index is required.
    """

    candidate_centroids = _positive_int(candidate_centroids, "candidate_centroids")
    if max_shards is None:
        max_shards = candidate_centroids * MAX_VECTOR_SHARDS_PER_CENTROID
    max_shards = _positive_int(max_shards, "max_shards")
    if not routing_rows:
        raise VectorRoutingError("vector routing meta-index is empty")

    np = _numpy()
    groups: dict[int, list[Mapping[str, Any]]] = {}
    dimensions: set[int] = set()
    for row in routing_rows:
        if not isinstance(row, Mapping):
            raise VectorRoutingError("routing row must be a mapping")
        cluster_id = int(row["cluster_id"])
        groups.setdefault(cluster_id, []).append(row)
        dimensions.add(int(row["dimension"]))
    if len(dimensions) != 1:
        raise VectorRoutingError("routing metadata mixes embedding dimensions")
    dimension = next(iter(dimensions))
    if dimension < 1:
        raise VectorRoutingError("routing dimension must be positive")

    query = np.asarray(list(query_embedding), dtype=np.float64)
    if query.shape != (dimension,) or not np.isfinite(query).all():
        raise VectorRoutingError("query embedding dimension or values differ")
    norm = float(np.linalg.norm(query))
    if not math.isfinite(norm) or norm == 0.0:
        raise VectorRoutingError("query embedding must be finite and non-zero")
    query = (query / norm).astype(np.float32)

    ranked: list[tuple[float, int, list[Mapping[str, Any]]]] = []
    for cluster_id, group in groups.items():
        ordered = sorted(group, key=lambda row: int(row["chunk_in_cluster"]))
        if [int(row["chunk_in_cluster"]) for row in ordered] != list(
            range(len(ordered))
        ):
            raise VectorRoutingError(
                f"cluster {cluster_id} chunk numbering differs"
            )
        if any(int(row["centroid_shard_count"]) != len(ordered) for row in ordered):
            raise VectorRoutingError(
                f"cluster {cluster_id} shard count differs"
            )
        centroid = np.asarray(ordered[0]["centroid"], dtype=np.float32)
        if centroid.shape != (dimension,):
            raise VectorRoutingError(
                f"cluster {cluster_id} centroid dimension differs"
            )
        for row in ordered[1:]:
            other = np.asarray(row["centroid"], dtype=np.float32)
            if not np.allclose(other, centroid, atol=NORM_TOLERANCE, rtol=0.0):
                raise VectorRoutingError(
                    f"cluster {cluster_id} routing centroid differs across shards"
                )
        centroid_norm = float(np.linalg.norm(centroid))
        if not math.isclose(centroid_norm, 1.0, abs_tol=NORM_TOLERANCE, rel_tol=0.0):
            raise VectorRoutingError(
                f"cluster {cluster_id} routing centroid is not normalized"
            )
        ranked.append((float(query @ centroid), cluster_id, ordered))

    if not ranked:
        raise VectorRoutingError("no searchable semantic centroids")
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


# ---------------------------------------------------------------------------
# Optional Parquet writers
# ---------------------------------------------------------------------------


def _shard_data_rows(shard: VectorShardSpec) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for offset, entry_cid in enumerate(shard.entry_cids):
        rows.append(
            {
                "chunk_in_cluster": shard.chunk_in_cluster,
                "cluster_id": shard.cluster_id,
                "document_index": shard.document_indexes[offset],
                "embedding": list(shard.embeddings[offset]),
                "entry_cid": entry_cid,
                "schema_version": VECTOR_CHUNK_SCHEMA_VERSION,
            }
        )
    return rows


def write_centroid_routed_vectors(
    rows: Sequence[Mapping[str, Any] | VectorRecord],
    output_root: str | Path,
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
    index_path: str = VECTOR_INDEX_PATH,
    write_index: bool = True,
) -> VectorLayoutWriteResult:
    """Build the layout and write ZSTD Parquet shards + optional routing index."""

    layout = build_centroid_routed_vector_layout(
        rows,
        seed=seed,
        max_rows_per_shard=max_rows_per_shard,
        max_shards_per_centroid=max_shards_per_centroid,
        max_rows_per_centroid=max_rows_per_centroid,
        target_rows_per_centroid=target_rows_per_centroid,
        max_centroids=max_centroids,
        kmeans_iterations=kmeans_iterations,
        max_training_rows=max_training_rows,
        data_dir=data_dir,
    )
    root = resolve_release_root(output_root, must_exist=False)
    root.mkdir(parents=True, exist_ok=True)
    config = ArtifactWriterConfig(max_rows_per_shard=layout.max_rows_per_shard)

    descriptors: list[Any] = []
    descriptor_map: dict[str, dict[str, Any]] = {}
    for shard in layout.shards:
        path = confine_path(root, shard.relative_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        write_zstd_parquet(
            path,
            _shard_data_rows(shard),
            max_rows=layout.max_rows_per_shard,
            config=config,
        )
        descriptor = describe_file(
            path,
            root=root,
            row_count=shard.row_count,
            family=ArtifactFamily.VECTORS,
            schema_id=VECTOR_CHUNK_SCHEMA_VERSION,
            first_key=shard.entry_cids[0] if shard.entry_cids else None,
            last_key=shard.entry_cids[-1] if shard.entry_cids else None,
            shard_id=shard.global_shard_id,
            metadata={
                "cluster_id": shard.cluster_id,
                "chunk_in_cluster": shard.chunk_in_cluster,
            },
        )
        descriptors.append(descriptor)
        descriptor_map[shard.relative_path] = descriptor.to_dict()

    routing_rows = layout.routing_rows(descriptors=descriptor_map)
    index_descriptor = None
    if write_index:
        index_relative = normalize_relative_artifact_path(index_path)
        index_file = confine_path(root, index_relative)
        index_file.parent.mkdir(parents=True, exist_ok=True)
        write_zstd_parquet(
            index_file,
            routing_rows,
            max_rows=MAX_ROWS_PER_PHYSICAL_SHARD,
            config=ArtifactWriterConfig(
                max_rows_per_shard=MAX_ROWS_PER_PHYSICAL_SHARD
            ),
        )
        index_descriptor = describe_file(
            index_file,
            root=root,
            row_count=len(routing_rows),
            family=ArtifactFamily.ROUTING_INDEX,
            schema_id=VECTOR_ROUTING_SCHEMA_VERSION,
        )

    return VectorLayoutWriteResult(
        layout=layout,
        data_descriptors=tuple(descriptors),
        routing_rows=routing_rows,
        routing_index_descriptor=index_descriptor,
        output_root=str(root),
    )


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def build_fixture_vector_rows(
    recipe: Mapping[str, Any],
) -> tuple[dict[str, Any], ...]:
    """Materialize compact fixture recipe rows into vector input mappings."""

    if not isinstance(recipe, Mapping):
        raise VectorInputError("fixture recipe must be a mapping")
    dimension = int(recipe.get("dimension", 2))
    if dimension < 1:
        raise VectorInputError("fixture dimension must be positive")
    rows_spec = recipe.get("rows")
    if not isinstance(rows_spec, Sequence):
        raise VectorInputError("fixture recipe.rows must be a sequence")
    rows: list[dict[str, Any]] = []
    for position, item in enumerate(rows_spec):
        if not isinstance(item, Mapping):
            raise VectorInputError(f"fixture rows[{position}] must be a mapping")
        entry_cid = str(item.get("entry_cid") or f"entry-{position:04d}")
        if "embedding" in item:
            embedding = [float(value) for value in item["embedding"]]
        elif "axis" in item:
            # One-hot / signed-axis recipe: {"axis": 0, "sign": 1.0}
            axis = int(item["axis"])
            sign = float(item.get("sign", 1.0))
            if axis < 0 or axis >= dimension:
                raise VectorInputError(
                    f"fixture axis {axis} out of range for dimension {dimension}"
                )
            embedding = [0.0] * dimension
            embedding[axis] = sign
        elif "direction" in item:
            # Compact 2-d polar recipe: angle in degrees.
            angle = math.radians(float(item["direction"]))
            embedding = [math.cos(angle), math.sin(angle)]
            if dimension > 2:
                embedding.extend([0.0] * (dimension - 2))
        else:
            raise VectorInputError(
                f"fixture rows[{position}] needs embedding, axis, or direction"
            )
        rows.append(
            {
                "document_index": int(item.get("document_index", position)),
                "embedding": embedding,
                "entry_cid": entry_cid,
            }
        )
    return tuple(rows)


def build_vector_clusters_fixture_payload(
    *,
    seed: int = DEFAULT_VECTOR_KMEANS_SEED,
    include_realized_layout: bool = True,
) -> dict[str, Any]:
    """Build the sealed unit-test fixture payload (compact recipes).

    The on-disk fixture stores the recipe and sealed bounds.  When
    *include_realized_layout* is true the payload also embeds the realized
    cluster summary and layout digest so tests can prove byte-stable
    regeneration without re-sealing large embedding dumps.
    """

    # Two opposing semantic lobes so clustering, two-shard split, cosine
    # order, and seed stability are all exercised without bulk goldens.
    recipe = {
        "dimension": 2,
        "rows": [
            {"entry_cid": "entry-a1", "direction": 0.0},
            {"entry_cid": "entry-a2", "direction": 5.0},
            {"entry_cid": "entry-a3", "direction": 10.0},
            {"entry_cid": "entry-a4", "direction": 15.0},
            {"entry_cid": "entry-b1", "direction": 180.0},
            {"entry_cid": "entry-b2", "direction": 185.0},
            {"entry_cid": "entry-b3", "direction": 190.0},
            {"entry_cid": "entry-b4", "direction": 175.0},
        ],
    }
    bounds = {
        "kmeans_iterations": DEFAULT_KMEANS_ITERATIONS,
        "max_rows_per_centroid": 4,
        "max_rows_per_shard": 2,
        "max_shards_per_centroid": 2,
        "seed": int(seed),
        "target_rows_per_centroid": 3,
    }
    rows = build_fixture_vector_rows(recipe)
    expected: dict[str, Any] = {
        "max_rows_per_centroid": bounds["max_rows_per_centroid"],
        "max_rows_per_shard": bounds["max_rows_per_shard"],
        "max_shards_per_centroid": bounds["max_shards_per_centroid"],
        "rows_sorted_by": ROWS_SORTED_BY,
        "seed": int(seed),
        "total_rows": len(rows),
        "unique_entry_cids": sorted(row["entry_cid"] for row in rows),
    }
    if include_realized_layout:
        layout = build_centroid_routed_vector_layout(rows, **bounds)
        cluster_summary = []
        for group in layout.clusters:
            cluster_summary.append(
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
                            "scores_desc": True,
                        }
                        for shard in group.shards
                    ],
                }
            )
        layout_digest = content_sha256(
            canonical_json_dumps(
                {
                    "clusters": [
                        {
                            "cluster_id": group.cluster_id,
                            "entry_cids": list(group.entry_cids),
                            "shards": [
                                {
                                    "chunk_in_cluster": shard.chunk_in_cluster,
                                    "entry_cids": list(shard.entry_cids),
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
            )
        )
        expected.update(
            {
                "cluster_count": layout.cluster_count,
                "cluster_summary": cluster_summary,
                "layout_digest": layout_digest,
                "shard_count": layout.shard_count,
            }
        )
    return {
        "assignment": ASSIGNMENT,
        "bounds": vector_bounds_policy(),
        "description": (
            "Compact deterministic recipes for USCIR-018 centroid-routed "
            "vector shard unit tests. Embeddings are regenerated from the "
            "recipe; structural expectations are derived deterministically."
        ),
        "expected": expected,
        "goal_id": GOAL_ID,
        "recipe": recipe,
        "schema_version": VECTOR_FIXTURE_SCHEMA_VERSION,
        "task_id": TASK_ID,
        "test_bounds": bounds,
    }


def default_vector_clusters_fixture_path() -> Path:
    """Return the sealed fixture path relative to the repository tests tree."""

    return (
        Path(__file__).resolve().parents[3]
        / "tests"
        / "fixtures"
        / "hf_graphrag"
        / "vector_clusters.json"
    )


def load_vector_clusters_fixture(
    path: str | Path | None = None,
) -> dict[str, Any]:
    """Load and lightly validate the vector-clusters fixture payload."""

    import json

    target = Path(path) if path is not None else default_vector_clusters_fixture_path()
    if not target.is_file():
        raise HfGraphragVectorError(f"vector clusters fixture missing: {target}")
    payload = json.loads(target.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise HfGraphragVectorError("vector clusters fixture must be a mapping")
    if payload.get("schema_version") != VECTOR_FIXTURE_SCHEMA_VERSION:
        raise HfGraphragVectorError(
            "vector clusters fixture schema_version differs"
        )
    if payload.get("task_id") != TASK_ID:
        raise HfGraphragVectorError("vector clusters fixture task_id differs")
    return dict(payload)


def layout_from_fixture(
    payload: Mapping[str, Any] | None = None,
    *,
    path: str | Path | None = None,
) -> VectorClusterLayout:
    """Rebuild a :class:`VectorClusterLayout` from the sealed fixture recipe."""

    data = dict(payload) if payload is not None else load_vector_clusters_fixture(path)
    recipe = data.get("recipe")
    if not isinstance(recipe, Mapping):
        raise HfGraphragVectorError("fixture recipe missing")
    bounds = data.get("test_bounds") or {}
    rows = build_fixture_vector_rows(recipe)
    return build_centroid_routed_vector_layout(
        rows,
        seed=int(bounds.get("seed", DEFAULT_VECTOR_KMEANS_SEED)),
        max_rows_per_shard=int(bounds.get("max_rows_per_shard", 2)),
        max_shards_per_centroid=int(bounds.get("max_shards_per_centroid", 2)),
        max_rows_per_centroid=int(bounds.get("max_rows_per_centroid", 4)),
        target_rows_per_centroid=int(bounds.get("target_rows_per_centroid", 3)),
        kmeans_iterations=int(
            bounds.get("kmeans_iterations", DEFAULT_KMEANS_ITERATIONS)
        ),
    )


__all__ = [
    "ASSIGNMENT",
    "DEFAULT_CANDIDATE_CENTROIDS",
    "DEFAULT_KMEANS_ITERATIONS",
    "DEFAULT_TARGET_ROWS_PER_CENTROID",
    "DEFAULT_VECTOR_KMEANS_SEED",
    "GOAL_ID",
    "MAX_ROWS_PER_PHYSICAL_SHARD",
    "MAX_ROWS_PER_VECTOR_CENTROID",
    "MAX_VECTOR_SHARDS_PER_CENTROID",
    "NORM_TOLERANCE",
    "ROWS_SORTED_BY",
    "TASK_ID",
    "VECTOR_CHUNK_SCHEMA_VERSION",
    "VECTOR_DATA_COLUMNS",
    "VECTOR_DATA_DIR",
    "VECTOR_FIXTURE_SCHEMA_VERSION",
    "VECTOR_INDEX_PATH",
    "VECTOR_LAYOUT_SCHEMA_VERSION",
    "VECTOR_META_COLUMNS",
    "VECTOR_ROUTING_SCHEMA_VERSION",
    "HfGraphragVectorError",
    "VectorClusterGroup",
    "VectorClusterLayout",
    "VectorCoverageError",
    "VectorInputError",
    "VectorLayoutWriteResult",
    "VectorOrderingError",
    "VectorRecord",
    "VectorRoutingError",
    "VectorShardRoute",
    "VectorShardSpec",
    "build_centroid_routed_vector_layout",
    "build_fixture_vector_rows",
    "build_vector_clusters_fixture_payload",
    "centroid_part_filename",
    "coerce_vector_records",
    "default_vector_clusters_fixture_path",
    "layout_from_fixture",
    "load_vector_clusters_fixture",
    "normalize_unit_matrix",
    "route_vector_shards",
    "validate_vector_layout",
    "vector_bounds_policy",
    "vector_shard_relative_path",
    "write_centroid_routed_vectors",
]
