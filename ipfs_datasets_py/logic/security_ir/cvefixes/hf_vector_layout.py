"""Deterministic Hugging Face vector shards for CVEfixes Security IR.

The layout intentionally mirrors the remotely routable vector portion of the
``Publicus/skillcenter-ir`` release:

* normalized vectors live in bounded Zstandard-compressed Parquet shards;
* ``indexes/vector_chunks.parquet`` contains compact routing centroids;
* every routing row binds its shard by SHA-256, CIDv1, byte size, and exact
  document range; and
* a thin client can rank the centroid index before downloading any data shard.

Production callers should pass ``require_embeddings=True``.  In that mode the
builder rejects an index with even one missing embedding and, by default,
requires an immutable model revision.  The neutral-row mode exists only so
tests and incomplete private builds can retain coverage without fabricating
semantic vectors.  Neutral rows are explicitly marked and never become
searchable vectors.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import hashlib
import heapq
import math
import os
from pathlib import Path, PurePosixPath
import re
from types import MappingProxyType
from typing import Any, Final

from ...ir_core.identity import cid_v1_from_digest
from .hf_release import HF_META_SCHEMA_VERSION
from .retrieval import NO_EMBEDDING_MODEL, RetrievalEntry, RetrievalIndex


CVEFIXES_HF_VECTOR_CHUNK_SCHEMA_VERSION: Final = (
    "cvefixes-hf-vector-chunk/v1"
)
VECTOR_CHUNK_ROWS: Final = 4096
VECTOR_MAX_SHARDS_PER_CENTROID: Final = 2
VECTOR_MAX_ROWS_PER_CENTROID: Final = (
    VECTOR_CHUNK_ROWS * VECTOR_MAX_SHARDS_PER_CENTROID
)
VECTOR_TARGET_ROWS_PER_CENTROID: Final = 2048
VECTOR_MAX_CENTROIDS: Final = 64
VECTOR_DEFAULT_PROBE_CENTROIDS: Final = 4
VECTOR_KMEANS_ITERATIONS: Final = 6
PARQUET_COMPRESSION: Final = "zstd"
PARQUET_COMPRESSION_LEVEL: Final = 6

_IMMUTABLE_REVISION_RE = re.compile(
    r"(?:[0-9a-f]{40}|[0-9a-f]{64}|sha256:[0-9a-f]{64}|b[a-z2-7]{20,})"
)
_VECTOR_PATH_RE = re.compile(r"data/vectors/part-(\d{6})\.parquet")
_BASE_META_FIELDS: Final[tuple[str, ...]] = (
    "cid",
    "end_document_index",
    "first_key",
    "kind",
    "last_key",
    "relative_path",
    "row_count",
    "schema_version",
    "sha256",
    "shard_id",
    "size_bytes",
    "start_document_index",
)
_VECTOR_META_FIELDS: Final[tuple[str, ...]] = (
    "centroid",
    "centroid_min_score",
    "centroid_shard_count",
    "chunk_in_cluster",
    "cluster_id",
    "dimension",
    "model_name",
    "shard_centroid",
)
VECTOR_META_COLUMNS: Final[tuple[str, ...]] = (
    *_BASE_META_FIELDS,
    *_VECTOR_META_FIELDS,
)
VECTOR_DATA_COLUMNS: Final[tuple[str, ...]] = (
    "chunk_id",
    "cluster_id",
    "entry_cid",
    "faiss_id",
    "document_index",
    "corpus_chunk_id",
    "corpus_row_offset",
    "node_cid",
    "retrieval_shard_id",
    "partition",
    "kind",
    "authority",
    "source_cids",
    "has_embedding",
    "embedding",
    "model_id",
    "model_revision",
    "model_config_cid",
    "retrieval_index_root",
    "schema_version",
)


class CVEfixesHFVectorLayoutError(ValueError):
    """Raised when a vector release cannot be built safely."""


class CVEfixesHFVectorIntegrityError(CVEfixesHFVectorLayoutError):
    """Raised when a vector artifact differs from its routing pointer."""


@dataclass(frozen=True, slots=True)
class VectorShardRoute:
    """One verified routing decision returned to a remote thin client."""

    cluster_id: int
    chunk_in_cluster: int
    score: float
    cid: str
    relative_path: str
    sha256: str
    size_bytes: int
    row_count: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "chunk_in_cluster": self.chunk_in_cluster,
            "cid": self.cid,
            "cluster_id": self.cluster_id,
            "relative_path": self.relative_path,
            "row_count": self.row_count,
            "score": self.score,
            "sha256": self.sha256,
            "size_bytes": self.size_bytes,
        }


@dataclass(frozen=True, slots=True)
class CVEfixesHFVectorLayoutSummary:
    """Materialized vector layout and the values needed by a release manifest."""

    output_root: str
    vector_rows: int
    embedded_rows: int
    neutral_rows: int
    dimension: int
    model_name: str
    cluster_count: int
    searchable_cluster_count: int
    vector_chunks: int
    meta_index: Mapping[str, Any]
    chunk_rows: tuple[Mapping[str, Any], ...]
    manifest_config: Mapping[str, Any]

    @property
    def searchable(self) -> bool:
        return self.embedded_rows > 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "chunk_rows": [dict(row) for row in self.chunk_rows],
            "cluster_count": self.cluster_count,
            "dimension": self.dimension,
            "embedded_rows": self.embedded_rows,
            "manifest_config": dict(self.manifest_config),
            "meta_index": dict(self.meta_index),
            "model_name": self.model_name,
            "neutral_rows": self.neutral_rows,
            "output_root": self.output_root,
            "searchable": self.searchable,
            "searchable_cluster_count": self.searchable_cluster_count,
            "vector_chunks": self.vector_chunks,
            "vector_rows": self.vector_rows,
        }


@dataclass(frozen=True, slots=True)
class _VectorRow:
    document_index: int
    retrieval_shard_id: str
    entry: RetrievalEntry


def build_cvefixes_hf_vector_layout(
    index: RetrievalIndex,
    output_root: str | Path,
    *,
    require_embeddings: bool = False,
    require_immutable_model_revision: bool | None = None,
    max_rows_per_shard: int = VECTOR_CHUNK_ROWS,
    max_shards_per_centroid: int = VECTOR_MAX_SHARDS_PER_CENTROID,
    target_rows_per_centroid: int = VECTOR_TARGET_ROWS_PER_CENTROID,
    max_centroids: int = VECTOR_MAX_CENTROIDS,
    kmeans_iterations: int = VECTOR_KMEANS_ITERATIONS,
) -> CVEfixesHFVectorLayoutSummary:
    """Write vector data shards and their compact routing meta-index.

    ``require_embeddings=True`` is the production switch.  It rejects empty
    or partially embedded indexes, rejects the sentinel ``none`` model, and
    makes immutable model-revision validation the default.  Set
    ``require_immutable_model_revision=False`` only when a different external
    mechanism already proves that the model revision is immutable.
    """

    if not isinstance(index, RetrievalIndex):
        raise CVEfixesHFVectorLayoutError("index must be a RetrievalIndex")
    for value, label in (
        (max_rows_per_shard, "max_rows_per_shard"),
        (max_shards_per_centroid, "max_shards_per_centroid"),
        (target_rows_per_centroid, "target_rows_per_centroid"),
        (max_centroids, "max_centroids"),
        (kmeans_iterations, "kmeans_iterations"),
    ):
        _positive_int(value, label)
    if max_shards_per_centroid > VECTOR_MAX_SHARDS_PER_CENTROID:
        raise CVEfixesHFVectorLayoutError(
            "SkillCenter-compatible routing permits at most two shards "
            "per centroid"
        )
    if max_rows_per_shard > VECTOR_CHUNK_ROWS:
        raise CVEfixesHFVectorLayoutError(
            f"SkillCenter-compatible vector shards permit at most "
            f"{VECTOR_CHUNK_ROWS} rows"
        )
    max_rows_per_centroid = max_rows_per_shard * max_shards_per_centroid
    if target_rows_per_centroid > max_rows_per_centroid:
        raise CVEfixesHFVectorLayoutError(
            "target_rows_per_centroid exceeds centroid capacity"
        )
    if require_immutable_model_revision is None:
        require_immutable_model_revision = require_embeddings
    if type(require_embeddings) is not bool:
        raise CVEfixesHFVectorLayoutError(
            "require_embeddings must be a boolean"
        )
    if type(require_immutable_model_revision) is not bool:
        raise CVEfixesHFVectorLayoutError(
            "require_immutable_model_revision must be a boolean"
        )

    rows = _index_rows(index)
    if not rows:
        raise CVEfixesHFVectorLayoutError(
            "cannot publish an empty vector layout"
        )
    dimension = index.embedding_dimension
    embedded_positions = tuple(
        row.document_index for row in rows if row.entry.embedding
    )
    neutral_positions = tuple(
        row.document_index for row in rows if not row.entry.embedding
    )
    if require_embeddings and neutral_positions:
        raise CVEfixesHFVectorLayoutError(
            "production vector layout requires an embedding for every row"
        )
    if require_embeddings and not embedded_positions:
        raise CVEfixesHFVectorLayoutError(
            "production vector layout cannot be embedding-free"
        )
    no_model = (
        index.model_id == NO_EMBEDDING_MODEL
        or index.model_revision == NO_EMBEDDING_MODEL
    )
    if embedded_positions and no_model:
        raise CVEfixesHFVectorLayoutError(
            "embedded rows must bind a real model and revision"
        )
    if require_immutable_model_revision and not _IMMUTABLE_REVISION_RE.fullmatch(
        index.model_revision
    ):
        raise CVEfixesHFVectorLayoutError(
            "production vector layout requires an immutable model revision "
            "(Hub commit SHA, SHA-256 digest, or CID)"
        )

    np = _numpy()
    matrix = np.zeros((len(rows), dimension), dtype=np.float32)
    for position in embedded_positions:
        vector = np.asarray(rows[position].entry.embedding, dtype=np.float64)
        if vector.shape != (dimension,) or not np.isfinite(vector).all():
            raise CVEfixesHFVectorLayoutError(
                "retrieval embedding matrix is malformed"
            )
        norm = float(np.linalg.norm(vector))
        if not math.isfinite(norm) or norm == 0.0:
            raise CVEfixesHFVectorLayoutError(
                "retrieval embeddings must be finite non-zero vectors"
            )
        normalized = (vector / norm).astype(np.float32)
        normalized_norm = float(np.linalg.norm(normalized))
        if not math.isfinite(normalized_norm) or normalized_norm == 0.0:
            raise CVEfixesHFVectorLayoutError(
                "retrieval embedding cannot be normalized as float32"
            )
        matrix[position] = normalized / normalized_norm

    groups = _routing_groups(
        matrix,
        embedded_positions=embedded_positions,
        neutral_positions=neutral_positions,
        target_rows_per_centroid=target_rows_per_centroid,
        max_rows_per_centroid=max_rows_per_centroid,
        max_centroids=max_centroids,
        kmeans_iterations=kmeans_iterations,
        np=np,
    )
    if (
        not groups
        or sum(len(group) for group in groups) != len(rows)
        or sorted(position for group in groups for position in group)
        != list(range(len(rows)))
        or max(map(len, groups)) > max_rows_per_centroid
    ):
        raise CVEfixesHFVectorIntegrityError(
            "vector centroid coverage is incomplete"
        )

    root = Path(output_root).expanduser().resolve()
    vector_dir = root / "data" / "vectors"
    meta_path = root / "indexes" / "vector_chunks.parquet"
    _ensure_fresh_destination(vector_dir, meta_path)
    vector_dir.mkdir(parents=True, exist_ok=True)
    meta_path.parent.mkdir(parents=True, exist_ok=True)

    pinned_model_name = (
        NO_EMBEDDING_MODEL
        if not embedded_positions
        else f"{index.model_id}@{index.model_revision}"
    )
    meta_rows: list[dict[str, Any]] = []
    shard_id = 0
    for cluster_id, group in enumerate(groups):
        group_positions = np.asarray(group, dtype=np.int64)
        routing_centroid = _unit_centroid(
            matrix, group_positions, np=np
        )
        physical_shards = _physical_shards(
            matrix,
            group_positions,
            max_rows_per_shard=max_rows_per_shard,
            kmeans_iterations=kmeans_iterations,
            np=np,
        )
        if not 1 <= len(physical_shards) <= max_shards_per_centroid:
            raise CVEfixesHFVectorIntegrityError(
                "routing centroid points to too many physical shards"
            )
        for chunk_in_cluster, selected in enumerate(physical_shards):
            shard_centroid = _unit_centroid(matrix, selected, np=np)
            has_embedding = np.linalg.norm(matrix[selected], axis=1) > 0.0
            scores = matrix[selected] @ shard_centroid
            ordered_offsets = sorted(
                range(len(selected)),
                key=lambda offset: (
                    not bool(has_embedding[offset]),
                    -float(scores[offset]),
                    int(selected[offset]),
                ),
            )
            selected = selected[np.asarray(ordered_offsets, dtype=np.int64)]
            has_embedding = has_embedding[
                np.asarray(ordered_offsets, dtype=np.int64)
            ]
            scores = scores[np.asarray(ordered_offsets, dtype=np.int64)]
            chunk_name = f"vector-{shard_id:06d}"
            table = _vector_table(
                rows,
                matrix,
                selected,
                cluster_id=cluster_id,
                chunk_name=chunk_name,
                index=index,
            )
            path = vector_dir / f"part-{shard_id:06d}.parquet"
            _write_parquet(path, table, max_rows=max_rows_per_shard)
            embedded_scores = [
                float(score)
                for score, present in zip(scores, has_embedding, strict=True)
                if bool(present)
            ]
            descriptor = _file_descriptor(path, root=root)
            entry_values = table["entry_cid"].to_pylist()
            document_values = table["document_index"].to_pylist()
            meta_rows.append(
                {
                    **descriptor,
                    "end_document_index": int(max(document_values)),
                    "first_key": str(entry_values[0]),
                    "kind": "vectors",
                    "last_key": str(entry_values[-1]),
                    "row_count": table.num_rows,
                    "schema_version": HF_META_SCHEMA_VERSION,
                    "shard_id": shard_id,
                    "start_document_index": int(min(document_values)),
                    "centroid": _float32_list(routing_centroid, np=np),
                    "centroid_min_score": _float32_scalar(
                        min(embedded_scores) if embedded_scores else 0.0,
                        np=np,
                    ),
                    "centroid_shard_count": len(physical_shards),
                    "chunk_in_cluster": chunk_in_cluster,
                    "cluster_id": cluster_id,
                    "dimension": dimension,
                    "model_name": pinned_model_name,
                    "shard_centroid": _float32_list(
                        shard_centroid, np=np
                    ),
                }
            )
            shard_id += 1

    _validate_layout(
        root,
        meta_rows,
        expected_rows=len(rows),
        expected_entry_cids={row.entry.entry_id for row in rows},
        require_embeddings=require_embeddings,
    )
    _write_meta_index(meta_path, meta_rows)
    persisted_rows = read_cvefixes_vector_meta_index(meta_path)
    _assert_meta_rows_equal(meta_rows, persisted_rows)
    meta_descriptor = _file_descriptor(meta_path, root=root)

    searchable_clusters = sum(
        1
        for cluster_id in range(len(groups))
        if any(
            _centroid_norm(row["centroid"]) > 0.0
            for row in meta_rows
            if int(row["cluster_id"]) == cluster_id
        )
    )
    manifest_config = {
        "assignment": "deterministic_balanced_spherical_kmeans",
        "centroid_count": len(groups),
        "default_probe_centroids": min(
            VECTOR_DEFAULT_PROBE_CENTROIDS, searchable_clusters
        ),
        "dimension": dimension,
        "embedded_rows": len(embedded_positions),
        "layout": "semantic_centroid_groups",
        "max_rows_per_centroid": max_rows_per_centroid,
        "max_rows_per_chunk": max_rows_per_shard,
        "max_shards_per_centroid": max_shards_per_centroid,
        "model_config_cid": index.model_config_cid,
        "model_id": index.model_id,
        "model_name": pinned_model_name,
        "model_revision": index.model_revision,
        "neutral_rows": len(neutral_positions),
        "retrieval_index_root": index.index_root,
        "rows_sorted_by": (
            "cosine_similarity_to_shard_centroid_desc"
            if not neutral_positions
            else (
                "has_embedding_desc_"
                "cosine_similarity_to_shard_centroid_desc"
            )
        ),
        "searchable": bool(embedded_positions),
        "searchable_centroid_count": searchable_clusters,
        "shard_count": len(meta_rows),
        "similarity": "cosine",
    }
    return CVEfixesHFVectorLayoutSummary(
        output_root=str(root),
        vector_rows=len(rows),
        embedded_rows=len(embedded_positions),
        neutral_rows=len(neutral_positions),
        dimension=dimension,
        model_name=pinned_model_name,
        cluster_count=len(groups),
        searchable_cluster_count=searchable_clusters,
        vector_chunks=len(meta_rows),
        meta_index=MappingProxyType(meta_descriptor),
        chunk_rows=tuple(
            MappingProxyType(dict(row)) for row in meta_rows
        ),
        manifest_config=MappingProxyType(manifest_config),
    )


def read_cvefixes_vector_meta_index(
    path: str | Path,
) -> tuple[dict[str, Any], ...]:
    """Read and strictly validate the compact vector routing table."""

    _, pq = _pyarrow()
    unresolved = Path(path).expanduser()
    if unresolved.is_symlink():
        raise CVEfixesHFVectorIntegrityError(
            f"vector meta-index must not be a symlink: {unresolved}"
        )
    source = unresolved.resolve()
    if not source.is_file():
        raise CVEfixesHFVectorIntegrityError(
            f"vector meta-index does not exist safely: {source}"
        )
    parquet = pq.ParquetFile(source)
    metadata = parquet.schema_arrow.metadata or {}
    if metadata.get(b"schema_version") != HF_META_SCHEMA_VERSION.encode():
        raise CVEfixesHFVectorIntegrityError(
            "vector meta-index schema version differs"
        )
    table = parquet.read()
    if tuple(table.column_names) != VECTOR_META_COLUMNS:
        raise CVEfixesHFVectorIntegrityError(
            "vector meta-index columns differ from the remote contract"
        )
    rows = tuple(dict(row) for row in table.to_pylist())
    if not rows:
        raise CVEfixesHFVectorIntegrityError(
            "vector meta-index must not be empty"
        )
    for row in rows:
        _validate_meta_row(row)
    return rows


def verify_cvefixes_vector_shard(
    output_root: str | Path,
    meta_row: Mapping[str, Any],
) -> Path:
    """Verify one local shard against a downloaded routing row."""

    _validate_meta_row(meta_row)
    root = Path(output_root).expanduser().resolve()
    relative_path = str(meta_row["relative_path"])
    match = _VECTOR_PATH_RE.fullmatch(relative_path)
    if match is None or int(match.group(1)) != int(meta_row["shard_id"]):
        raise CVEfixesHFVectorIntegrityError(
            "vector shard path and shard_id differ"
        )
    parsed = PurePosixPath(relative_path)
    path = root.joinpath(*parsed.parts)
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise CVEfixesHFVectorIntegrityError(
            "vector shard path escapes the release root"
        ) from exc
    if path.is_symlink() or not path.is_file():
        raise CVEfixesHFVectorIntegrityError(
            f"vector shard does not exist safely: {relative_path}"
        )
    descriptor = _file_descriptor(path, root=root)
    for name in ("cid", "relative_path", "sha256", "size_bytes"):
        if descriptor[name] != meta_row[name]:
            raise CVEfixesHFVectorIntegrityError(
                f"vector shard {name} differs: {relative_path}"
            )

    _, pq = _pyarrow()
    parquet = pq.ParquetFile(path)
    metadata = parquet.schema_arrow.metadata or {}
    if (
        metadata.get(b"schema_version")
        != CVEFIXES_HF_VECTOR_CHUNK_SCHEMA_VERSION.encode()
    ):
        raise CVEfixesHFVectorIntegrityError(
            f"vector shard schema version differs: {relative_path}"
        )
    table = parquet.read()
    if tuple(table.column_names) != VECTOR_DATA_COLUMNS:
        raise CVEfixesHFVectorIntegrityError(
            f"vector shard columns differ: {relative_path}"
        )
    if table.num_rows != int(meta_row["row_count"]):
        raise CVEfixesHFVectorIntegrityError(
            f"vector shard row count differs: {relative_path}"
        )
    if table.num_rows < 1 or table.num_rows > VECTOR_CHUNK_ROWS:
        raise CVEfixesHFVectorIntegrityError(
            f"vector shard row bound differs: {relative_path}"
        )
    expected_chunk = f"vector-{int(meta_row['shard_id']):06d}"
    if set(table["chunk_id"].to_pylist()) != {expected_chunk}:
        raise CVEfixesHFVectorIntegrityError(
            f"vector chunk identity differs: {relative_path}"
        )
    if set(table["cluster_id"].to_pylist()) != {
        int(meta_row["cluster_id"])
    }:
        raise CVEfixesHFVectorIntegrityError(
            f"vector cluster identity differs: {relative_path}"
        )
    entry_cids = table["entry_cid"].to_pylist()
    documents = [int(value) for value in table["document_index"].to_pylist()]
    if (
        str(entry_cids[0]) != str(meta_row["first_key"])
        or str(entry_cids[-1]) != str(meta_row["last_key"])
        or min(documents) != int(meta_row["start_document_index"])
        or max(documents) != int(meta_row["end_document_index"])
    ):
        raise CVEfixesHFVectorIntegrityError(
            f"vector shard key/document range differs: {relative_path}"
        )

    np = _numpy()
    dimension = int(meta_row["dimension"])
    vectors = np.asarray(table["embedding"].to_pylist(), dtype=np.float32)
    if vectors.shape != (table.num_rows, dimension):
        raise CVEfixesHFVectorIntegrityError(
            f"vector shard dimension differs: {relative_path}"
        )
    present = np.asarray(
        table["has_embedding"].to_pylist(), dtype=np.bool_
    )
    norms = np.linalg.norm(vectors, axis=1)
    if (
        bool((present & ~np.isclose(norms, 1.0, atol=2e-6)).any())
        or bool((~present & ~np.isclose(norms, 0.0, atol=0.0)).any())
    ):
        raise CVEfixesHFVectorIntegrityError(
            f"vector normalization/neutral marker differs: {relative_path}"
        )
    shard_centroid = np.asarray(
        meta_row["shard_centroid"], dtype=np.float32
    )
    expected_shard_centroid = _unit_centroid(
        vectors, np.arange(table.num_rows, dtype=np.int64), np=np
    )
    if shard_centroid.shape != (dimension,) or not np.allclose(
        shard_centroid, expected_shard_centroid, atol=2e-6, rtol=0.0
    ):
        raise CVEfixesHFVectorIntegrityError(
            f"vector shard centroid differs: {relative_path}"
        )
    scores = vectors @ shard_centroid
    observed_order = [
        (
            not bool(present[offset]),
            -float(scores[offset]),
            documents[offset],
        )
        for offset in range(table.num_rows)
    ]
    if observed_order != sorted(observed_order):
        raise CVEfixesHFVectorIntegrityError(
            f"vector shard ordering differs: {relative_path}"
        )
    embedded_scores = scores[present]
    expected_min = (
        float(embedded_scores.min()) if len(embedded_scores) else 0.0
    )
    if not math.isclose(
        float(meta_row["centroid_min_score"]),
        expected_min,
        abs_tol=2e-6,
        rel_tol=0.0,
    ):
        raise CVEfixesHFVectorIntegrityError(
            f"vector shard minimum score differs: {relative_path}"
        )
    return path


def route_cvefixes_vector_shards(
    meta_rows: Sequence[Mapping[str, Any]],
    query_embedding: Sequence[float],
    *,
    candidate_centroids: int = VECTOR_DEFAULT_PROBE_CENTROIDS,
    max_shards: int = (
        VECTOR_DEFAULT_PROBE_CENTROIDS
        * VECTOR_MAX_SHARDS_PER_CENTROID
    ),
    expected_model_name: str | None = None,
) -> tuple[VectorShardRoute, ...]:
    """Rank routing centroids without reading any vector data shard."""

    _positive_int(candidate_centroids, "candidate_centroids")
    _positive_int(max_shards, "max_shards")
    if not meta_rows:
        raise CVEfixesHFVectorLayoutError(
            "vector routing meta-index is empty"
        )
    for row in meta_rows:
        _validate_meta_row(row)
    dimensions = {int(row["dimension"]) for row in meta_rows}
    model_names = {str(row["model_name"]) for row in meta_rows}
    if len(dimensions) != 1 or len(model_names) != 1:
        raise CVEfixesHFVectorIntegrityError(
            "vector routing metadata mixes dimensions or models"
        )
    dimension = next(iter(dimensions))
    model_name = next(iter(model_names))
    if expected_model_name is not None and model_name != expected_model_name:
        raise CVEfixesHFVectorIntegrityError(
            "query model binding differs from vector routing metadata"
        )
    if dimension < 1:
        raise CVEfixesHFVectorLayoutError(
            "neutral vector layout is not semantically searchable"
        )
    np = _numpy()
    query = np.asarray(query_embedding, dtype=np.float64)
    if query.shape != (dimension,) or not np.isfinite(query).all():
        raise CVEfixesHFVectorLayoutError(
            "query embedding dimension or values differ"
        )
    norm = float(np.linalg.norm(query))
    if not math.isfinite(norm) or norm == 0.0:
        raise CVEfixesHFVectorLayoutError(
            "query embedding must be finite and non-zero"
        )
    query = (query / norm).astype(np.float32)

    groups: dict[int, list[Mapping[str, Any]]] = {}
    for row in meta_rows:
        groups.setdefault(int(row["cluster_id"]), []).append(row)
    ranked: list[tuple[float, int, list[Mapping[str, Any]]]] = []
    for cluster_id, group in groups.items():
        ordered = sorted(
            group, key=lambda row: int(row["chunk_in_cluster"])
        )
        if [int(row["chunk_in_cluster"]) for row in ordered] != list(
            range(len(ordered))
        ):
            raise CVEfixesHFVectorIntegrityError(
                "vector centroid chunk numbering differs"
            )
        if any(
            int(row["centroid_shard_count"]) != len(ordered)
            for row in ordered
        ):
            raise CVEfixesHFVectorIntegrityError(
                "vector centroid shard count differs"
            )
        centroid = np.asarray(ordered[0]["centroid"], dtype=np.float32)
        if centroid.shape != (dimension,) or any(
            not np.array_equal(
                np.asarray(row["centroid"], dtype=np.float32), centroid
            )
            for row in ordered[1:]
        ):
            raise CVEfixesHFVectorIntegrityError(
                "vector routing centroid differs across its shards"
            )
        centroid_norm = float(np.linalg.norm(centroid))
        if math.isclose(centroid_norm, 0.0, abs_tol=0.0):
            # Explicit neutral clusters never participate in semantic routing.
            continue
        if not math.isclose(
            centroid_norm, 1.0, abs_tol=2e-6, rel_tol=0.0
        ):
            raise CVEfixesHFVectorIntegrityError(
                "vector routing centroid is not normalized"
            )
        ranked.append(
            (float(query @ centroid), cluster_id, ordered)
        )
    if not ranked:
        raise CVEfixesHFVectorLayoutError(
            "vector layout has no searchable semantic centroids"
        )
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
                    cid=str(row["cid"]),
                    relative_path=str(row["relative_path"]),
                    sha256=str(row["sha256"]),
                    size_bytes=int(row["size_bytes"]),
                    row_count=int(row["row_count"]),
                )
            )
    return tuple(routes)


def _index_rows(index: RetrievalIndex) -> tuple[_VectorRow, ...]:
    pairs = [
        (entry, shard.shard_id)
        for shard in index.shards
        for entry in shard.entries
    ]
    pairs.sort(key=lambda item: item[0].entry_id)
    return tuple(
        _VectorRow(
            document_index=document_index,
            retrieval_shard_id=shard_id,
            entry=entry,
        )
        for document_index, (entry, shard_id) in enumerate(pairs)
    )


def _routing_groups(
    matrix: Any,
    *,
    embedded_positions: Sequence[int],
    neutral_positions: Sequence[int],
    target_rows_per_centroid: int,
    max_rows_per_centroid: int,
    max_centroids: int,
    kmeans_iterations: int,
    np: Any,
) -> list[list[int]]:
    if not embedded_positions:
        cluster_count = math.ceil(
            len(neutral_positions) / max_rows_per_centroid
        )
        if cluster_count > max_centroids:
            raise CVEfixesHFVectorLayoutError(
                "neutral vector layout exceeds the centroid bound"
            )
        return [
            list(group)
            for group in _balanced_position_groups(
                neutral_positions, cluster_count
            )
        ]

    required = math.ceil(
        len(embedded_positions) / max_rows_per_centroid
    )
    desired = math.ceil(
        len(embedded_positions) / target_rows_per_centroid
    )
    cluster_count = max(1, required, desired)
    if cluster_count > max_centroids:
        raise CVEfixesHFVectorLayoutError(
            "vector row count exceeds the bounded centroid layout"
        )
    cluster_count = min(cluster_count, len(embedded_positions))
    embedded_array = np.asarray(embedded_positions, dtype=np.int64)
    centroids = _learn_centroids(
        matrix,
        embedded_array,
        cluster_count,
        iterations=kmeans_iterations,
        np=np,
    )
    assignments = _capacity_constrained_assignments(
        matrix[embedded_array] @ centroids.T,
        np=np,
    )
    groups = [
        [
            int(value)
            for value in embedded_array[
                np.flatnonzero(assignments == cluster_id)
            ]
        ]
        for cluster_id in range(cluster_count)
    ]
    for position in neutral_positions:
        candidates = [
            (len(group), cluster_id)
            for cluster_id, group in enumerate(groups)
            if len(group) < max_rows_per_centroid
        ]
        if not candidates:
            if len(groups) >= max_centroids:
                raise CVEfixesHFVectorLayoutError(
                    "neutral rows exceed remaining centroid capacity"
                )
            groups.append([int(position)])
            continue
        _, cluster_id = min(candidates)
        groups[cluster_id].append(int(position))
    return groups


def _physical_shards(
    matrix: Any,
    positions: Any,
    *,
    max_rows_per_shard: int,
    kmeans_iterations: int,
    np: Any,
) -> list[Any]:
    shard_count = math.ceil(len(positions) / max_rows_per_shard)
    if shard_count == 1:
        return [positions]
    if shard_count > VECTOR_MAX_SHARDS_PER_CENTROID:
        raise CVEfixesHFVectorIntegrityError(
            "centroid requires more than two physical shards"
        )
    embedded = positions[
        np.linalg.norm(matrix[positions], axis=1) > 0.0
    ]
    if len(embedded) < shard_count:
        return [
            np.asarray(group, dtype=np.int64)
            for group in _balanced_position_groups(
                [int(value) for value in positions], shard_count
            )
        ]
    centroids = _learn_centroids(
        matrix,
        embedded,
        shard_count,
        iterations=kmeans_iterations,
        np=np,
    )
    assignments = _capacity_constrained_assignments(
        matrix[positions] @ centroids.T,
        np=np,
    )
    return [
        positions[np.flatnonzero(assignments == shard_id)]
        for shard_id in range(shard_count)
    ]


def _learn_centroids(
    matrix: Any,
    positions: Any,
    cluster_count: int,
    *,
    iterations: int,
    np: Any,
) -> Any:
    if cluster_count < 1 or cluster_count > len(positions):
        raise CVEfixesHFVectorLayoutError(
            "semantic centroid count is malformed"
        )
    selected: list[int] = [0]
    while len(selected) < cluster_count:
        centroids = matrix[positions[np.asarray(selected, dtype=np.int64)]]
        nearest = (matrix[positions] @ centroids.T).max(axis=1)
        nearest[np.asarray(selected, dtype=np.int64)] = np.inf
        candidate = int(np.argmin(nearest))
        selected.append(candidate)
    centroids = matrix[
        positions[np.asarray(selected, dtype=np.int64)]
    ].copy()
    for _ in range(iterations):
        assignments = np.argmax(matrix[positions] @ centroids.T, axis=1)
        updated = centroids.copy()
        for cluster_id in range(cluster_count):
            members = positions[
                np.flatnonzero(assignments == cluster_id)
            ]
            if not len(members):
                continue
            candidate = _unit_centroid(matrix, members, np=np)
            if float(np.linalg.norm(candidate)) == 0.0:
                candidate = matrix[int(members.min())]
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
        raise CVEfixesHFVectorLayoutError(
            "centroid score matrix is malformed"
        )
    row_count, cluster_count = values.shape
    capacities = _balanced_capacities(row_count, cluster_count)
    preferences = np.argsort(-values, axis=1, kind="stable")
    next_preference = np.zeros(row_count, dtype=np.int32)
    assignments = np.full(row_count, -1, dtype=np.int32)
    accepted: list[list[tuple[float, int, int]]] = [
        [] for _ in range(cluster_count)
    ]
    pending = deque(range(row_count))
    while pending:
        row_id = int(pending.popleft())
        rank = int(next_preference[row_id])
        if rank >= cluster_count:
            raise CVEfixesHFVectorIntegrityError(
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
        or list(np.bincount(assignments, minlength=cluster_count))
        != capacities
    ):
        raise CVEfixesHFVectorIntegrityError(
            "balanced centroid assignment coverage differs"
        )
    return assignments


def _balanced_capacities(
    row_count: int, group_count: int
) -> list[int]:
    if group_count < 1 or group_count > row_count:
        raise CVEfixesHFVectorLayoutError(
            "balanced group count is malformed"
        )
    base, remainder = divmod(row_count, group_count)
    return [
        base + (1 if group_id < remainder else 0)
        for group_id in range(group_count)
    ]


def _balanced_position_groups(
    positions: Sequence[int], group_count: int
) -> tuple[tuple[int, ...], ...]:
    capacities = _balanced_capacities(len(positions), group_count)
    groups = []
    offset = 0
    for capacity in capacities:
        groups.append(
            tuple(int(value) for value in positions[offset : offset + capacity])
        )
        offset += capacity
    return tuple(groups)


def _unit_centroid(matrix: Any, positions: Any, *, np: Any) -> Any:
    selected = matrix[positions]
    present = np.linalg.norm(selected, axis=1) > 0.0
    if not bool(present.any()):
        return np.zeros(matrix.shape[1], dtype=np.float32)
    centroid = selected[present].astype(np.float64).mean(axis=0)
    norm = float(np.linalg.norm(centroid))
    if not math.isfinite(norm) or norm == 0.0:
        # Opposing vectors can have an exact zero mean.  The lowest document
        # index is a deterministic, meaningful member-vector fallback.
        centroid = selected[int(np.flatnonzero(present)[0])].astype(
            np.float64
        )
        norm = float(np.linalg.norm(centroid))
    result = (centroid / norm).astype(np.float32)
    result_norm = float(np.linalg.norm(result))
    return (result / result_norm).astype(np.float32)


def _vector_table(
    rows: Sequence[_VectorRow],
    matrix: Any,
    selected: Any,
    *,
    cluster_id: int,
    chunk_name: str,
    index: RetrievalIndex,
) -> Any:
    pa, _ = _pyarrow()
    dimension = matrix.shape[1]
    values = [rows[int(position)] for position in selected]
    documents = [item.document_index for item in values]
    embeddings = [
        [float(value) for value in matrix[int(position)]]
        for position in selected
    ]
    schema = pa.schema(
        [
            ("chunk_id", pa.string(), False),
            ("cluster_id", pa.int32(), False),
            ("entry_cid", pa.string(), False),
            ("faiss_id", pa.int64(), False),
            ("document_index", pa.int64(), False),
            ("corpus_chunk_id", pa.int32(), False),
            ("corpus_row_offset", pa.int32(), False),
            ("node_cid", pa.string(), False),
            ("retrieval_shard_id", pa.string(), False),
            ("partition", pa.string(), False),
            ("kind", pa.string(), False),
            ("authority", pa.string(), False),
            ("source_cids", pa.list_(pa.string()), False),
            ("has_embedding", pa.bool_(), False),
            (
                "embedding",
                (
                    pa.list_(pa.float32(), dimension)
                    if dimension
                    else pa.list_(pa.float32())
                ),
                False,
            ),
            ("model_id", pa.string(), False),
            ("model_revision", pa.string(), False),
            ("model_config_cid", pa.string(), False),
            ("retrieval_index_root", pa.string(), False),
            ("schema_version", pa.string(), False),
        ],
        metadata={
            b"schema_version": (
                CVEFIXES_HF_VECTOR_CHUNK_SCHEMA_VERSION.encode()
            )
        },
    )
    return pa.Table.from_pydict(
        {
            "chunk_id": [chunk_name] * len(values),
            "cluster_id": [cluster_id] * len(values),
            "entry_cid": [item.entry.entry_id for item in values],
            "faiss_id": documents,
            "document_index": documents,
            "corpus_chunk_id": [
                value // VECTOR_CHUNK_ROWS for value in documents
            ],
            "corpus_row_offset": [
                value % VECTOR_CHUNK_ROWS for value in documents
            ],
            "node_cid": [item.entry.node_cid for item in values],
            "retrieval_shard_id": [
                item.retrieval_shard_id for item in values
            ],
            "partition": [item.entry.partition for item in values],
            "kind": [item.entry.kind for item in values],
            "authority": [item.entry.authority.value for item in values],
            "source_cids": [
                list(item.entry.source_cids) for item in values
            ],
            "has_embedding": [
                bool(item.entry.embedding) for item in values
            ],
            "embedding": embeddings,
            "model_id": [index.model_id] * len(values),
            "model_revision": [index.model_revision] * len(values),
            "model_config_cid": [index.model_config_cid] * len(values),
            "retrieval_index_root": [index.index_root] * len(values),
            "schema_version": [
                CVEFIXES_HF_VECTOR_CHUNK_SCHEMA_VERSION
            ]
            * len(values),
        },
        schema=schema,
    )


def _validate_layout(
    root: Path,
    meta_rows: Sequence[Mapping[str, Any]],
    *,
    expected_rows: int,
    expected_entry_cids: set[str],
    require_embeddings: bool,
) -> None:
    _, pq = _pyarrow()
    if [int(row["shard_id"]) for row in meta_rows] != list(
        range(len(meta_rows))
    ):
        raise CVEfixesHFVectorIntegrityError(
            "vector shard identifiers are not contiguous"
        )
    observed_documents: list[int] = []
    observed_entry_cids: list[str] = []
    cluster_vectors: dict[int, list[Any]] = {}
    cluster_rows: dict[int, list[Mapping[str, Any]]] = {}
    embedded_rows = 0
    for row in meta_rows:
        path = verify_cvefixes_vector_shard(root, row)
        table = pq.read_table(
            path,
            columns=[
                "document_index",
                "entry_cid",
                "embedding",
                "has_embedding",
            ],
        )
        observed_documents.extend(
            int(value) for value in table["document_index"].to_pylist()
        )
        observed_entry_cids.extend(
            str(value) for value in table["entry_cid"].to_pylist()
        )
        vectors = table["embedding"].to_pylist()
        present = table["has_embedding"].to_pylist()
        embedded_rows += sum(bool(value) for value in present)
        cluster_vectors.setdefault(int(row["cluster_id"]), []).extend(
            vector
            for vector, available in zip(vectors, present, strict=True)
            if bool(available)
        )
        cluster_rows.setdefault(int(row["cluster_id"]), []).append(row)
    if (
        sorted(observed_documents) != list(range(expected_rows))
        or len(observed_documents) != len(set(observed_documents))
        or set(observed_entry_cids) != expected_entry_cids
        or len(observed_entry_cids) != len(set(observed_entry_cids))
    ):
        raise CVEfixesHFVectorIntegrityError(
            "vector shard document/entry coverage differs"
        )
    if require_embeddings and embedded_rows != expected_rows:
        raise CVEfixesHFVectorIntegrityError(
            "production vector layout contains neutral rows"
        )
    if sorted(cluster_rows) != list(range(len(cluster_rows))):
        raise CVEfixesHFVectorIntegrityError(
            "vector cluster identifiers are not contiguous"
        )
    np = _numpy()
    for cluster_id, rows in cluster_rows.items():
        ordered = sorted(
            rows, key=lambda row: int(row["chunk_in_cluster"])
        )
        if (
            [int(row["chunk_in_cluster"]) for row in ordered]
            != list(range(len(ordered)))
            or any(
                int(row["centroid_shard_count"]) != len(ordered)
                for row in ordered
            )
        ):
            raise CVEfixesHFVectorIntegrityError(
                f"vector cluster {cluster_id} shard coverage differs"
            )
        dimension = int(ordered[0]["dimension"])
        vectors = np.asarray(
            cluster_vectors.get(cluster_id, []), dtype=np.float32
        )
        if len(vectors):
            expected = _unit_centroid(
                vectors,
                np.arange(len(vectors), dtype=np.int64),
                np=np,
            )
        else:
            expected = np.zeros(dimension, dtype=np.float32)
        for row in ordered:
            observed = np.asarray(row["centroid"], dtype=np.float32)
            if observed.shape != (dimension,) or not np.allclose(
                observed, expected, atol=2e-6, rtol=0.0
            ):
                raise CVEfixesHFVectorIntegrityError(
                    f"vector routing centroid {cluster_id} differs"
                )


def _validate_meta_row(row: Mapping[str, Any]) -> None:
    if not isinstance(row, Mapping) or set(row) != set(VECTOR_META_COLUMNS):
        raise CVEfixesHFVectorIntegrityError(
            "vector meta row fields differ from the remote contract"
        )
    for name in (
        "row_count",
        "size_bytes",
        "centroid_shard_count",
        "dimension",
    ):
        value = row[name]
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            if name == "dimension" and value == 0:
                continue
            raise CVEfixesHFVectorIntegrityError(
                f"vector meta row {name} is malformed"
            )
    for name in (
        "shard_id",
        "cluster_id",
        "chunk_in_cluster",
        "start_document_index",
        "end_document_index",
    ):
        value = row[name]
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise CVEfixesHFVectorIntegrityError(
                f"vector meta row {name} is malformed"
            )
    if int(row["start_document_index"]) > int(
        row["end_document_index"]
    ):
        raise CVEfixesHFVectorIntegrityError(
            "vector meta row document range is malformed"
        )
    if row["kind"] != "vectors" or row["schema_version"] != HF_META_SCHEMA_VERSION:
        raise CVEfixesHFVectorIntegrityError(
            "vector meta row kind/schema version differs"
        )
    if not re.fullmatch(r"[0-9a-f]{64}", str(row["sha256"])):
        raise CVEfixesHFVectorIntegrityError(
            "vector meta row SHA-256 is malformed"
        )
    if not re.fullmatch(r"b[a-z2-7]{20,}", str(row["cid"])):
        raise CVEfixesHFVectorIntegrityError(
            "vector meta row CID is malformed"
        )
    dimension = int(row["dimension"])
    for name in ("centroid", "shard_centroid"):
        values = row[name]
        if (
            isinstance(values, (str, bytes, bytearray))
            or not isinstance(values, Sequence)
            or len(values) != dimension
            or any(
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(float(value))
                for value in values
            )
        ):
            raise CVEfixesHFVectorIntegrityError(
                f"vector meta row {name} is malformed"
            )
    score = row["centroid_min_score"]
    if (
        isinstance(score, bool)
        or not isinstance(score, (int, float))
        or not math.isfinite(float(score))
        or not -1.000001 <= float(score) <= 1.000001
    ):
        raise CVEfixesHFVectorIntegrityError(
            "vector meta row centroid_min_score is malformed"
        )
    for name in ("first_key", "last_key", "model_name", "relative_path"):
        value = row[name]
        if not isinstance(value, str) or not value or value != value.strip():
            raise CVEfixesHFVectorIntegrityError(
                f"vector meta row {name} is malformed"
            )


def _assert_meta_rows_equal(
    expected: Sequence[Mapping[str, Any]],
    observed: Sequence[Mapping[str, Any]],
) -> None:
    if len(expected) != len(observed):
        raise CVEfixesHFVectorIntegrityError(
            "persisted vector meta-index row count differs"
        )
    for expected_row, observed_row in zip(expected, observed, strict=True):
        for name in VECTOR_META_COLUMNS:
            left = expected_row[name]
            right = observed_row[name]
            if isinstance(left, list):
                if [float(value) for value in left] != [
                    float(value) for value in right
                ]:
                    raise CVEfixesHFVectorIntegrityError(
                        f"persisted vector meta-index {name} differs"
                    )
            elif left != right:
                raise CVEfixesHFVectorIntegrityError(
                    f"persisted vector meta-index {name} differs"
                )


def _write_meta_index(
    path: Path, rows: Sequence[Mapping[str, Any]]
) -> None:
    pa, _ = _pyarrow()
    schema = pa.schema(
        [
            ("cid", pa.string(), False),
            ("end_document_index", pa.int64(), False),
            ("first_key", pa.string(), False),
            ("kind", pa.string(), False),
            ("last_key", pa.string(), False),
            ("relative_path", pa.string(), False),
            ("row_count", pa.int64(), False),
            ("schema_version", pa.string(), False),
            ("sha256", pa.string(), False),
            ("shard_id", pa.int32(), False),
            ("size_bytes", pa.int64(), False),
            ("start_document_index", pa.int64(), False),
            ("centroid", pa.list_(pa.float32()), False),
            ("centroid_min_score", pa.float32(), False),
            ("centroid_shard_count", pa.int32(), False),
            ("chunk_in_cluster", pa.int32(), False),
            ("cluster_id", pa.int32(), False),
            ("dimension", pa.int32(), False),
            ("model_name", pa.string(), False),
            ("shard_centroid", pa.list_(pa.float32()), False),
        ],
        metadata={b"schema_version": HF_META_SCHEMA_VERSION.encode()},
    )
    table = pa.Table.from_pylist(list(rows), schema=schema)
    _write_parquet(path, table, max_rows=None)


def _ensure_fresh_destination(vector_dir: Path, meta_path: Path) -> None:
    existing = []
    if vector_dir.exists():
        if vector_dir.is_symlink():
            raise CVEfixesHFVectorLayoutError(
                f"vector release destination is a symlink: {vector_dir}"
            )
        existing.extend(vector_dir.iterdir())
    if meta_path.exists() or meta_path.is_symlink():
        existing.append(meta_path)
    if existing:
        raise CVEfixesHFVectorLayoutError(
            "vector release destination already contains artifacts: "
            + ", ".join(str(path) for path in sorted(existing))
        )


def _write_parquet(
    path: Path, table: Any, *, max_rows: int | None
) -> None:
    _, pq = _pyarrow()
    if table.num_rows < 1:
        raise CVEfixesHFVectorLayoutError(
            f"cannot write an empty Parquet shard: {path}"
        )
    if max_rows is not None and table.num_rows > max_rows:
        raise CVEfixesHFVectorLayoutError(
            f"Parquet shard exceeds {max_rows} rows: {path}"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.partial")
    pq.write_table(
        table,
        temporary,
        compression=PARQUET_COMPRESSION,
        compression_level=PARQUET_COMPRESSION_LEVEL,
        row_group_size=max_rows or VECTOR_CHUNK_ROWS,
        use_dictionary=True,
        write_statistics=True,
    )
    parquet = pq.ParquetFile(temporary)
    compressions = {
        parquet.metadata.row_group(group).column(column).compression
        for group in range(parquet.num_row_groups)
        for column in range(
            parquet.metadata.row_group(group).num_columns
        )
    }
    if compressions and compressions != {"ZSTD"}:
        temporary.unlink(missing_ok=True)
        raise CVEfixesHFVectorIntegrityError(
            f"Parquet shard is not uniformly ZSTD-compressed: {path}"
        )
    os.replace(temporary, path)


def _file_descriptor(path: Path, *, root: Path) -> dict[str, Any]:
    digest = hashlib.sha256()
    size_bytes = 0
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
            size_bytes += len(chunk)
    raw_digest = digest.digest()
    return {
        "cid": cid_v1_from_digest(raw_digest),
        "relative_path": path.relative_to(root).as_posix(),
        "sha256": raw_digest.hex(),
        "size_bytes": size_bytes,
    }


def _centroid_norm(values: Sequence[float]) -> float:
    return math.sqrt(sum(float(value) ** 2 for value in values))


def _float32_list(values: Any, *, np: Any) -> list[float]:
    return [
        float(value)
        for value in np.asarray(values, dtype=np.float32).tolist()
    ]


def _float32_scalar(value: float, *, np: Any) -> float:
    return float(np.float32(value))


def _positive_int(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise CVEfixesHFVectorLayoutError(
            f"{label} must be a positive integer"
        )
    return value


def _numpy() -> Any:
    try:
        import numpy as np
    except ImportError as exc:  # pragma: no cover - optional dependency guard
        raise CVEfixesHFVectorLayoutError(
            "numpy is required to build CVEfixes vector shards"
        ) from exc
    return np


def _pyarrow() -> tuple[Any, Any]:
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ImportError as exc:  # pragma: no cover - optional dependency guard
        raise CVEfixesHFVectorLayoutError(
            "pyarrow is required to build CVEfixes vector shards"
        ) from exc
    return pa, pq
