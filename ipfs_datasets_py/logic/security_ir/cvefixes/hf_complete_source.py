"""Pinned control-plane reader for the complete CVEfixes Hub release.

The complete GraphRAG publication and the legacy canonical-row publication are
different physical contracts.  :mod:`.hf_source` deliberately reconstructs
canonical ``DerivedDataset`` records from homogeneous Parquet shards.  The
complete publication instead contains corpus, BM25, graph, vector, and
byte-exact source-mirror shards with independent schemas.

This module verifies that complete layout without pretending that its physical
rows are canonical Security IR records.  A Hub fetch downloads only:

* ``manifest.json``;
* ``release-metadata.json``; and
* the nine Parquet routing indexes below ``indexes/``.

The manifest binds every data shard by SHA-256 and raw-file CID.  The routing
indexes are downloaded and content-verified, then checked against those
descriptors.  The original-row index is checked as a complete position
bijection over the pinned upstream shards.  Raw original code is never opened
or copied into this cache.
"""

from __future__ import annotations

import base64
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import tempfile
from typing import Any, Final, Protocol, runtime_checkable

from ...ir_core.canonical import canonical_json_bytes
from .hf_release import HF_PARQUET_SCHEMA_VERSION, HF_RELEASE_SCHEMA_VERSION
from .hf_source import (
    HuggingFaceSourceCacheMiss,
    HuggingFaceSourceError,
    HuggingFaceSourceIntegrityError,
    HuggingFaceSourceLimitError,
    HuggingFaceSourcePin,
)
from .schemas import ReleaseManifest


HF_COMPLETE_SOURCE_SCHEMA_VERSION: Final = (
    "cvefixes-huggingface-complete-source/v1"
)
HF_COMPLETE_SOURCE_CACHE_SCHEMA_VERSION: Final = (
    "cvefixes-huggingface-complete-source-cache/v1"
)
COMPLETE_BUILD_SCHEMA_VERSION: Final = "cvefixes-complete-hf-build/v1"
COMPLETE_METADATA_PATH: Final = "release-metadata.json"
ORIGINAL_MIRROR_PROFILE: Final = "cvefixes-byte-preserving-mirror/v1"
DERIVED_SECURITY_IR_PROFILE: Final = "public-metadata-and-body-digests"
META_SCHEMA_VERSION: Final = "cvefixes-hf-shard-meta/v1"
ORIGINAL_ROW_INDEX_SCHEMA_VERSION: Final = (
    "cvefixes-hf-original-row-index/v1"
)
PINNED_SOURCE_DATASET_ID: Final = "hitoshura25/cvefixes"
PINNED_SOURCE_REVISION: Final = (
    "d4f5c4ea65329d9ccbb8a3b3149e5d06eda5edb2"
)
PINNED_SOURCE_PROFILE_SHA256: Final = (
    "163e267f9ffd9b5d0193dc26014b775c8ebb7dc804772473ef8a6aa8bd3eb3d1"
)

_SHA256_RE: Final = re.compile(r"[0-9a-f]{64}")
_CID_RE: Final = re.compile(r"b[a-z2-7]{58}")
_PART_RE: Final = re.compile(r"part-(\d{6})\.parquet")
_MODEL_REVISION_RE: Final = re.compile(r"[0-9a-f]{40}")
_PARQUET_MEDIA_TYPE: Final = "application/vnd.apache.parquet"
_CONTROL_ALLOW_PATTERNS: Final[tuple[str, ...]] = (
    "manifest.json",
    COMPLETE_METADATA_PATH,
    "indexes/*.parquet",
)

_MANIFEST_FIELDS: Final = frozenset(
    {
        "artifacts",
        "bm25",
        "build_runtime",
        "configs",
        "counts",
        "dataset_id",
        "derived_dataset_root",
        "graph",
        "indexes",
        "parquet",
        "primary_key",
        "release_manifest",
        "release_root",
        "schema_version",
        "source",
        "vector",
    }
)
_ARTIFACT_FIELDS: Final = frozenset(
    {"byte_length", "content_id", "media_type", "path", "sha256"}
)
_PARQUET_ARTIFACT_FIELDS: Final = _ARTIFACT_FIELDS | {
    "config_name",
    "row_count",
}
_COMPACT_DESCRIPTOR_FIELDS: Final = frozenset(
    {
        "cid",
        "relative_path",
        "row_count",
        "sha256",
        "size_bytes",
    }
)

_DATA_CONFIG_PREFIXES: Final[Mapping[str, str]] = {
    "bm25_documents": "data/bm25/documents/",
    "bm25_postings": "data/bm25/postings/",
    "corpus": "data/corpus/",
    "graph_edges": "data/graph/edges/",
    "graph_incoming_adjacency": "data/graph/adjacency/incoming/",
    "graph_nodes": "data/graph/nodes/",
    "graph_outgoing_adjacency": "data/graph/adjacency/outgoing/",
    "original_data": "data/original/",
    "vectors": "data/vectors/",
}
_DATA_CONFIG_PATTERNS: Final[Mapping[str, str]] = {
    name: f"{prefix}*.parquet"
    for name, prefix in _DATA_CONFIG_PREFIXES.items()
}
_INDEX_CONFIGS: Final[Mapping[str, str]] = {
    "bm25_document_chunks": "bm25_document_chunk_index",
    "bm25_keyword_shards": "bm25_keyword_index",
    "corpus_chunks": "corpus_chunk_index",
    "graph_edge_chunks": "graph_edge_chunk_index",
    "graph_incoming_adjacency": "graph_incoming_adjacency_index",
    "graph_node_chunks": "graph_node_chunk_index",
    "graph_outgoing_adjacency": "graph_outgoing_adjacency_index",
    "original_rows": "original_row_index",
    "vector_chunks": "vector_meta_index",
}
_INDEX_PATHS: Final[Mapping[str, str]] = {
    name: f"indexes/{name}.parquet" for name in _INDEX_CONFIGS
}
_INDEX_FAMILIES: Final[Mapping[str, str]] = {
    "bm25_document_chunks": "bm25_documents",
    "bm25_keyword_shards": "bm25_postings",
    "corpus_chunks": "corpus",
    "graph_edge_chunks": "graph_edges",
    "graph_incoming_adjacency": "graph_incoming_adjacency",
    "graph_node_chunks": "graph_nodes",
    "graph_outgoing_adjacency": "graph_outgoing_adjacency",
    "original_rows": "original_data",
    "vector_chunks": "vectors",
}
_VIEWER_INDEXES: Final = frozenset(
    {
        "bm25_keyword_shards",
        "corpus_chunks",
        "graph_incoming_adjacency",
        "graph_outgoing_adjacency",
        "original_rows",
        "vector_chunks",
    }
)
_VIEWER_CONFIGS: Final = frozenset(
    {*_DATA_CONFIG_PREFIXES, *(_INDEX_CONFIGS[name] for name in _VIEWER_INDEXES)}
)

_META_COLUMNS: Final = (
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
_INDEX_COLUMNS: Final[Mapping[str, tuple[str, ...]]] = {
    "bm25_document_chunks": _META_COLUMNS,
    "bm25_keyword_shards": (
        *_META_COLUMNS,
        "posting_count",
        "term_count",
        "token_instance_count",
    ),
    "corpus_chunks": _META_COLUMNS,
    "graph_edge_chunks": _META_COLUMNS,
    "graph_incoming_adjacency": (
        *_META_COLUMNS,
        "adjacency_count",
        "direction",
        "first_page_index",
        "last_page_index",
        "node_count",
    ),
    "graph_node_chunks": _META_COLUMNS,
    "graph_outgoing_adjacency": (
        *_META_COLUMNS,
        "adjacency_count",
        "direction",
        "first_page_index",
        "last_page_index",
        "node_count",
    ),
    "vector_chunks": (
        *_META_COLUMNS,
        "centroid",
        "centroid_min_score",
        "centroid_shard_count",
        "chunk_in_cluster",
        "cluster_id",
        "dimension",
        "model_name",
        "shard_centroid",
    ),
}
_ORIGINAL_ROW_COLUMNS: Final = (
    "security_ir_source_cid",
    "source_row_index",
    "source_status",
    "source_identity_domain",
    "source_identity_schema_version",
    "source_shard_cid",
    "source_shard_path",
    "source_shard_row_index",
    "relative_path",
    "source_dataset_id",
    "source_revision",
    "schema_version",
)
_STATUS_IDENTITY: Final[Mapping[str, tuple[str, str]]] = {
    "admitted": (
        "cvefixes-security-ir/pinned-source-row",
        "cvefixes-pinned-source-row/v1",
    ),
    "adaptation_rejected": (
        "cvefixes-security-ir/rejected-source-row",
        "cvefixes-rejected-source-row/v1",
    ),
    "publication_rejected": (
        "cvefixes-security-ir/rejected-source-row",
        "cvefixes-rejected-source-row/v1",
    ),
}


@dataclass(frozen=True, slots=True)
class _OriginalShardContract:
    release_path: str
    source_path: str
    sha256: str
    size_bytes: int
    row_count: int

    @property
    def cid(self) -> str:
        return _raw_sha256_cid(bytes.fromhex(self.sha256))


PINNED_ORIGINAL_SHARDS: Final[tuple[_OriginalShardContract, ...]] = (
    _OriginalShardContract(
        release_path="data/original/part-000000.parquet",
        source_path="data/train-00000-of-00003.parquet",
        sha256=(
            "2e25e84e85e1560d41acacbfc7eb359349f5417bc9bf31318cdf0c4aafccb7d1"
        ),
        size_bytes=211_599_861,
        row_count=4_329,
    ),
    _OriginalShardContract(
        release_path="data/original/part-000001.parquet",
        source_path="data/train-00001-of-00003.parquet",
        sha256=(
            "3a4251f39955f95c232b4aea98daa59bbe0c7b5e27c9189c1b09f64b960a35d7"
        ),
        size_bytes=428_366_432,
        row_count=4_329,
    ),
    _OriginalShardContract(
        release_path="data/original/part-000002.parquet",
        source_path="data/train-00002-of-00003.parquet",
        sha256=(
            "55488d569ac978ea077be643233355f43458d636d04ad3ae1cb973895b02a3ac"
        ),
        size_bytes=580_353_186,
        row_count=4_329,
    ),
)


def _positive_int(value: Any, label: str) -> int:
    if type(value) is not int or value <= 0:
        raise HuggingFaceSourceLimitError(f"{label} must be a positive integer")
    return value


def _raw_sha256_cid(digest: bytes) -> str:
    if len(digest) != 32:
        raise HuggingFaceSourceIntegrityError("invalid SHA-256 digest length")
    payload = bytes((0x01, 0x55, 0x12, 0x20)) + digest
    return "b" + base64.b32encode(payload).decode("ascii").lower().rstrip("=")


def _strict_json_object(content: bytes, label: str) -> Mapping[str, Any]:
    def object_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise HuggingFaceSourceIntegrityError(
                    f"{label} contains duplicate key {key!r}"
                )
            result[key] = value
        return result

    def reject_constant(value: str) -> Any:
        raise HuggingFaceSourceIntegrityError(
            f"{label} contains non-finite number {value}"
        )

    try:
        value = json.loads(
            content,
            object_pairs_hook=object_pairs,
            parse_constant=reject_constant,
        )
    except HuggingFaceSourceIntegrityError:
        raise
    except (UnicodeError, ValueError, TypeError) as exc:
        raise HuggingFaceSourceIntegrityError(
            f"{label} is not strict UTF-8 JSON"
        ) from exc
    if not isinstance(value, Mapping):
        raise HuggingFaceSourceIntegrityError(f"{label} must contain an object")
    return value


def _relative_path(value: Any) -> str:
    if (
        not isinstance(value, str)
        or not value
        or "\\" in value
        or "\x00" in value
    ):
        raise HuggingFaceSourceIntegrityError(
            "artifact path must be normalized root-relative POSIX text"
        )
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or path.as_posix() != value
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise HuggingFaceSourceIntegrityError("artifact path is unsafe")
    return value


def _safe_file(root: Path, relative_path: str) -> Path:
    path = root.joinpath(*PurePosixPath(_relative_path(relative_path)).parts)
    if path.is_symlink() or not path.is_file():
        raise HuggingFaceSourceIntegrityError(
            f"required control artifact is missing: {relative_path}"
        )
    try:
        path.resolve(strict=True).relative_to(root)
    except (OSError, ValueError) as exc:
        raise HuggingFaceSourceIntegrityError(
            f"control artifact escapes snapshot: {relative_path}"
        ) from exc
    return path


def _bounded_bytes(path: Path, maximum: int, label: str) -> bytes:
    if path.stat().st_size > maximum:
        raise HuggingFaceSourceLimitError(f"{label} exceeds byte limit")
    try:
        return path.read_bytes()
    except OSError as exc:
        raise HuggingFaceSourceIntegrityError(f"cannot read {label}") from exc


@dataclass(frozen=True, slots=True)
class _ArtifactDescriptor:
    path: str
    sha256: str
    content_id: str
    byte_length: int
    media_type: str
    config_name: str = ""
    row_count: int = 0

    @classmethod
    def from_dict(cls, value: Any) -> "_ArtifactDescriptor":
        if not isinstance(value, Mapping):
            raise HuggingFaceSourceIntegrityError(
                "artifact descriptor must be an object"
            )
        path = _relative_path(value.get("path"))
        expected = (
            _PARQUET_ARTIFACT_FIELDS
            if path.endswith(".parquet")
            else _ARTIFACT_FIELDS
        )
        if set(value) != expected:
            raise HuggingFaceSourceIntegrityError(
                f"artifact descriptor fields differ: {path}"
            )
        sha256 = value.get("sha256")
        content_id = value.get("content_id")
        byte_length = value.get("byte_length")
        media_type = value.get("media_type")
        if not isinstance(sha256, str) or not _SHA256_RE.fullmatch(sha256):
            raise HuggingFaceSourceIntegrityError(
                f"artifact SHA-256 is invalid: {path}"
            )
        if (
            not isinstance(content_id, str)
            or not _CID_RE.fullmatch(content_id)
            or content_id != _raw_sha256_cid(bytes.fromhex(sha256))
        ):
            raise HuggingFaceSourceIntegrityError(
                f"artifact CID is invalid: {path}"
            )
        if type(byte_length) is not int or byte_length <= 0:
            raise HuggingFaceSourceIntegrityError(
                f"artifact byte length is invalid: {path}"
            )
        if not isinstance(media_type, str) or not media_type:
            raise HuggingFaceSourceIntegrityError(
                f"artifact media type is invalid: {path}"
            )
        if path.endswith(".parquet"):
            config_name = value.get("config_name")
            row_count = value.get("row_count")
            if (
                media_type != _PARQUET_MEDIA_TYPE
                or not isinstance(config_name, str)
                or not config_name
                or type(row_count) is not int
                or row_count <= 0
            ):
                raise HuggingFaceSourceIntegrityError(
                    f"Parquet descriptor is invalid: {path}"
                )
        else:
            config_name = ""
            row_count = 0
        return cls(
            path=path,
            sha256=sha256,
            content_id=content_id,
            byte_length=byte_length,
            media_type=media_type,
            config_name=config_name,
            row_count=row_count,
        )

    def compact(self) -> dict[str, Any]:
        return {
            "cid": self.content_id,
            "relative_path": self.path,
            "row_count": self.row_count,
            "sha256": self.sha256,
            "size_bytes": self.byte_length,
        }


@dataclass(frozen=True, slots=True)
class HuggingFaceCompleteReleaseLimits:
    """Bounds for the small complete-release control plane."""

    max_manifest_bytes: int = 8 * 1024 * 1024
    max_metadata_bytes: int = 2 * 1024 * 1024
    max_index_bytes: int = 16 * 1024 * 1024
    max_artifacts: int = 512
    max_indexes: int = 16
    max_index_rows: int = 250_000
    max_data_shards: int = 512

    def __post_init__(self) -> None:
        for name in (
            "max_manifest_bytes",
            "max_metadata_bytes",
            "max_index_bytes",
            "max_artifacts",
            "max_indexes",
            "max_index_rows",
            "max_data_shards",
        ):
            _positive_int(getattr(self, name), name)


@dataclass(frozen=True, slots=True)
class HuggingFaceCompleteReleaseReceipt:
    """Verification summary; it contains no source bodies or policy authority."""

    dataset_id: str
    revision: str
    manifest_sha256: str
    release_root: str
    derived_dataset_root: str
    graph_root: str
    retrieval_index_root: str
    artifact_count: int
    control_artifact_count: int
    data_shard_count: int
    index_count: int
    canonical_record_count: int
    corpus_row_count: int
    graph_node_count: int
    graph_edge_count: int
    vector_row_count: int
    original_shard_count: int
    original_row_count: int
    original_byte_count: int
    offline: bool
    verified: bool = True
    raw_originals_loaded: bool = False
    grants_execution_authority: bool = False

    def __post_init__(self) -> None:
        if self.verified is not True:
            raise HuggingFaceSourceIntegrityError(
                "complete-release receipt must be verified"
            )
        if self.raw_originals_loaded is not False:
            raise HuggingFaceSourceIntegrityError(
                "complete-release verifier cannot load raw originals"
            )
        if self.grants_execution_authority is not False:
            raise HuggingFaceSourceIntegrityError(
                "complete-release verification cannot grant authority"
            )


@dataclass(frozen=True, slots=True)
class LoadedHuggingFaceCompleteRelease:
    """Pinned complete-release control plane, intentionally without records."""

    pin: HuggingFaceSourcePin
    receipt: HuggingFaceCompleteReleaseReceipt

    def __post_init__(self) -> None:
        if not isinstance(self.pin, HuggingFaceSourcePin):
            raise TypeError("pin must be a HuggingFaceSourcePin")
        if not isinstance(self.receipt, HuggingFaceCompleteReleaseReceipt):
            raise TypeError(
                "receipt must be a HuggingFaceCompleteReleaseReceipt"
            )
        if (
            self.receipt.dataset_id != self.pin.dataset_id
            or self.receipt.revision != self.pin.revision
            or self.receipt.manifest_sha256 != self.pin.manifest_sha256
            or self.receipt.release_root != self.pin.release_root
        ):
            raise HuggingFaceSourceIntegrityError(
                "complete-release receipt does not preserve the pin"
            )


def _verify_file(
    root: Path,
    descriptor: _ArtifactDescriptor,
    *,
    maximum: int,
) -> Path:
    path = _safe_file(root, descriptor.path)
    if descriptor.byte_length > maximum or path.stat().st_size > maximum:
        raise HuggingFaceSourceLimitError(
            f"control artifact exceeds byte limit: {descriptor.path}"
        )
    if path.stat().st_size != descriptor.byte_length:
        raise HuggingFaceSourceIntegrityError(
            f"control artifact size differs: {descriptor.path}"
        )
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            while chunk := handle.read(1024 * 1024):
                digest.update(chunk)
    except OSError as exc:
        raise HuggingFaceSourceIntegrityError(
            f"cannot hash control artifact: {descriptor.path}"
        ) from exc
    if (
        digest.hexdigest() != descriptor.sha256
        or _raw_sha256_cid(digest.digest()) != descriptor.content_id
    ):
        raise HuggingFaceSourceIntegrityError(
            f"control artifact identity differs: {descriptor.path}"
        )
    return path


def _data_config(path: str) -> str | None:
    for config, prefix in _DATA_CONFIG_PREFIXES.items():
        if path.startswith(prefix) and _PART_RE.fullmatch(path[len(prefix) :]):
            return config
    return None


def _validate_artifact_inventory(
    raw: Any,
    *,
    limits: HuggingFaceCompleteReleaseLimits,
) -> tuple[_ArtifactDescriptor, ...]:
    if (
        isinstance(raw, (str, bytes, bytearray))
        or not isinstance(raw, Sequence)
        or not raw
        or len(raw) > limits.max_artifacts
    ):
        raise HuggingFaceSourceLimitError(
            "complete artifact inventory is empty or exceeds limit"
        )
    artifacts = tuple(_ArtifactDescriptor.from_dict(item) for item in raw)
    paths = tuple(item.path for item in artifacts)
    if paths != tuple(sorted(paths)) or len(paths) != len(set(paths)):
        raise HuggingFaceSourceIntegrityError(
            "complete artifact inventory must be sorted and unique"
        )
    if "dataset_infos.json" in paths:
        raise HuggingFaceSourceIntegrityError(
            "complete release cannot contain reserved dataset_infos.json"
        )
    required = {"README.md", COMPLETE_METADATA_PATH, "evaluation-report.json"}
    if not required <= set(paths):
        raise HuggingFaceSourceIntegrityError(
            "complete release is missing public metadata"
        )
    unknown = tuple(
        item.path
        for item in artifacts
        if item.path not in required
        and _data_config(item.path) is None
        and item.path not in set(_INDEX_PATHS.values())
    )
    if unknown:
        raise HuggingFaceSourceIntegrityError(
            "complete release contains an unknown artifact path"
        )
    data = tuple(item for item in artifacts if _data_config(item.path))
    if not data or len(data) > limits.max_data_shards:
        raise HuggingFaceSourceLimitError(
            "complete data-shard inventory is empty or exceeds limit"
        )
    observed_configs = {_data_config(item.path) for item in data}
    if observed_configs != set(_DATA_CONFIG_PREFIXES):
        raise HuggingFaceSourceIntegrityError(
            "complete data-family inventory is incomplete"
        )
    for item in data:
        if item.config_name != _data_config(item.path):
            raise HuggingFaceSourceIntegrityError(
                f"data config differs from path: {item.path}"
            )
    indexes = tuple(item for item in artifacts if item.path.startswith("indexes/"))
    if len(indexes) > limits.max_indexes:
        raise HuggingFaceSourceLimitError("complete release exceeds index limit")
    if {item.path for item in indexes} != set(_INDEX_PATHS.values()):
        raise HuggingFaceSourceIntegrityError(
            "complete physical-index inventory is incomplete"
        )
    expected_index_config = {
        _INDEX_PATHS[name]: config for name, config in _INDEX_CONFIGS.items()
    }
    for item in indexes:
        if item.config_name != expected_index_config[item.path]:
            raise HuggingFaceSourceIntegrityError(
                f"index config differs from path: {item.path}"
            )
    return artifacts


def _validate_config_routes(
    manifest: Mapping[str, Any],
    artifacts: Sequence[_ArtifactDescriptor],
) -> None:
    configs = manifest.get("configs")
    if not isinstance(configs, Mapping):
        raise HuggingFaceSourceIntegrityError("manifest configs must be an object")
    expected = {
        **_DATA_CONFIG_PATTERNS,
        **{
            _INDEX_CONFIGS[name]: path
            for name, path in _INDEX_PATHS.items()
        },
    }
    if dict(configs) != expected:
        raise HuggingFaceSourceIntegrityError(
            "complete manifest config routes differ"
        )
    indexes = manifest.get("indexes")
    if not isinstance(indexes, Mapping) or set(indexes) != set(_INDEX_PATHS):
        raise HuggingFaceSourceIntegrityError(
            "complete manifest index inventory differs"
        )
    by_path = {item.path: item for item in artifacts}
    for name, path in _INDEX_PATHS.items():
        value = indexes[name]
        if (
            not isinstance(value, Mapping)
            or set(value) != _COMPACT_DESCRIPTOR_FIELDS
            or dict(value) != by_path[path].compact()
        ):
            raise HuggingFaceSourceIntegrityError(
                f"manifest index descriptor differs: {name}"
            )


def _read_index_table(
    root: Path,
    descriptor: _ArtifactDescriptor,
    *,
    limits: HuggingFaceCompleteReleaseLimits,
) -> Any:
    path = _verify_file(root, descriptor, maximum=limits.max_index_bytes)
    try:
        import pyarrow.parquet as pq

        parquet = pq.ParquetFile(path)
        if parquet.metadata.num_rows > limits.max_index_rows:
            raise HuggingFaceSourceLimitError(
                f"index exceeds row limit: {descriptor.path}"
            )
        table = parquet.read()
    except HuggingFaceSourceLimitError:
        raise
    except Exception as exc:
        raise HuggingFaceSourceIntegrityError(
            f"cannot decode index: {descriptor.path}"
        ) from exc
    if table.num_rows != descriptor.row_count:
        raise HuggingFaceSourceIntegrityError(
            f"index row count differs: {descriptor.path}"
        )
    return table


def _validate_route_indexes(
    root: Path,
    artifacts: Sequence[_ArtifactDescriptor],
    *,
    limits: HuggingFaceCompleteReleaseLimits,
) -> int:
    by_path = {item.path: item for item in artifacts}
    covered: set[str] = set()
    for name in sorted(set(_INDEX_PATHS) - {"original_rows"}):
        descriptor = by_path[_INDEX_PATHS[name]]
        table = _read_index_table(root, descriptor, limits=limits)
        if tuple(table.schema.names) != _INDEX_COLUMNS[name]:
            raise HuggingFaceSourceIntegrityError(
                f"index schema differs: {descriptor.path}"
            )
        metadata = table.schema.metadata or {}
        if metadata.get(b"schema_version") != META_SCHEMA_VERSION.encode("ascii"):
            raise HuggingFaceSourceIntegrityError(
                f"index schema version differs: {descriptor.path}"
            )
        rows = table.to_pylist()
        shard_ids: set[int] = set()
        family = _INDEX_FAMILIES[name]
        family_paths = {
            item.path
            for item in artifacts
            if item.config_name == family and _data_config(item.path) == family
        }
        routed: set[str] = set()
        for row in rows:
            path = row.get("relative_path")
            target = by_path.get(path)
            shard_id = row.get("shard_id")
            if (
                not isinstance(path, str)
                or path not in family_paths
                or path in routed
                or target is None
                or type(shard_id) is not int
                or shard_id < 0
                or shard_id in shard_ids
                or row.get("cid") != target.content_id
                or row.get("sha256") != target.sha256
                or row.get("size_bytes") != target.byte_length
                or row.get("row_count") != target.row_count
                or row.get("kind") != family
                or row.get("schema_version") != META_SCHEMA_VERSION
            ):
                raise HuggingFaceSourceIntegrityError(
                    f"index route binding differs: {descriptor.path}"
                )
            routed.add(path)
            shard_ids.add(shard_id)
        if routed != family_paths or shard_ids != set(range(len(rows))):
            raise HuggingFaceSourceIntegrityError(
                f"index does not cover its data family: {descriptor.path}"
            )
        covered.update(routed)
    expected = {
        item.path
        for item in artifacts
        if _data_config(item.path) not in {None, "original_data"}
    }
    if covered != expected:
        raise HuggingFaceSourceIntegrityError(
            "routing indexes do not cover derived data shards exactly"
        )
    return len(covered)


def _validate_original_manifest(
    manifest: Mapping[str, Any],
    artifacts: Sequence[_ArtifactDescriptor],
    release_manifest: ReleaseManifest,
) -> tuple[int, int, int]:
    by_path = {item.path: item for item in artifacts}
    originals = tuple(
        item for item in artifacts if item.config_name == "original_data"
    )
    if tuple(item.path for item in originals) != tuple(
        contract.release_path for contract in PINNED_ORIGINAL_SHARDS
    ):
        raise HuggingFaceSourceIntegrityError(
            "pinned original-shard inventory differs"
        )
    for item, contract in zip(originals, PINNED_ORIGINAL_SHARDS, strict=True):
        if (
            item.sha256 != contract.sha256
            or item.content_id != contract.cid
            or item.byte_length != contract.size_bytes
            or item.row_count != contract.row_count
        ):
            raise HuggingFaceSourceIntegrityError(
                f"pinned original-shard descriptor differs: {item.path}"
            )
    if (
        release_manifest.profile != ORIGINAL_MIRROR_PROFILE
        or release_manifest.payload.get("derived_security_ir_profile")
        != DERIVED_SECURITY_IR_PROFILE
    ):
        raise HuggingFaceSourceIntegrityError(
            "complete release mirror profile differs"
        )
    source = manifest.get("source")
    runtime = manifest.get("build_runtime")
    counts = manifest.get("counts")
    parquet = manifest.get("parquet")
    if not all(
        isinstance(value, Mapping)
        for value in (source, runtime, counts, parquet)
    ):
        raise HuggingFaceSourceIntegrityError(
            "complete original-data metadata is malformed"
        )
    assert isinstance(source, Mapping)
    assert isinstance(runtime, Mapping)
    assert isinstance(counts, Mapping)
    assert isinstance(parquet, Mapping)
    original = runtime.get("original_data")
    source_verification = runtime.get("source_verification")
    compression = parquet.get("compression")
    if not all(
        isinstance(value, Mapping)
        for value in (original, source_verification, compression)
    ):
        raise HuggingFaceSourceIntegrityError(
            "complete source runtime metadata is malformed"
        )
    assert isinstance(original, Mapping)
    assert isinstance(source_verification, Mapping)
    assert isinstance(compression, Mapping)
    expected_runtime_shards = [
        {
            "content_id": contract.cid,
            "release_path": contract.release_path,
            "row_count": contract.row_count,
            "sha256": contract.sha256,
            "size_bytes": contract.size_bytes,
            "source_path": contract.source_path,
        }
        for contract in PINNED_ORIGINAL_SHARDS
    ]
    original_rows = sum(item.row_count for item in originals)
    original_bytes = sum(item.byte_length for item in originals)
    row_index = by_path[_INDEX_PATHS["original_rows"]]
    if (
        source.get("dataset_id") != PINNED_SOURCE_DATASET_ID
        or source.get("source_revision") != PINNED_SOURCE_REVISION
        or original.get("byte_exact_upstream_copy") is not True
        or original.get("config_name") != "original_data"
        or original.get("mirror_profile") != ORIGINAL_MIRROR_PROFILE
        or original.get("operator_acknowledgement_required") is not True
        or original.get("row_index_config_name") != "original_row_index"
        or original.get("source_dataset_id") != PINNED_SOURCE_DATASET_ID
        or original.get("source_revision") != PINNED_SOURCE_REVISION
        or original.get("source_profile_sha256")
        != PINNED_SOURCE_PROFILE_SHA256
        or original.get("shards") != expected_runtime_shards
        or source_verification.get("verified") is not True
        or source_verification.get("profile_sha256")
        != PINNED_SOURCE_PROFILE_SHA256
        or source_verification.get("row_count") != original_rows
        or source_verification.get("shard_count") != len(originals)
        or counts.get("original_data_bytes") != original_bytes
        or counts.get("original_data_rows") != original_rows
        or counts.get("original_data_shards") != len(originals)
        or counts.get("original_row_index_rows") != row_index.row_count
        or row_index.row_count != original_rows
        or compression.get("derived_and_indexes") != "zstd"
        or compression.get("original_data") != "upstream_byte_exact"
        or parquet.get("physical_index_count") != len(_INDEX_PATHS)
    ):
        raise HuggingFaceSourceIntegrityError(
            "complete original-data binding differs"
        )
    return len(originals), original_rows, original_bytes


def _validate_original_row_index(
    root: Path,
    artifacts: Sequence[_ArtifactDescriptor],
    manifest: Mapping[str, Any],
    *,
    limits: HuggingFaceCompleteReleaseLimits,
) -> None:
    by_path = {item.path: item for item in artifacts}
    descriptor = by_path[_INDEX_PATHS["original_rows"]]
    table = _read_index_table(root, descriptor, limits=limits)
    if tuple(table.schema.names) != _ORIGINAL_ROW_COLUMNS:
        raise HuggingFaceSourceIntegrityError(
            "original-row index schema differs"
        )
    metadata = table.schema.metadata or {}
    if (
        metadata.get(b"schema_version")
        != ORIGINAL_ROW_INDEX_SCHEMA_VERSION.encode("ascii")
        or metadata.get(b"primary_key") != b"security_ir_source_cid"
    ):
        raise HuggingFaceSourceIntegrityError(
            "original-row index schema metadata differs"
        )
    positions = bytearray(descriptor.row_count)
    source_rows = bytearray(descriptor.row_count)
    source_cids: set[str] = set()
    status_counts = {name: 0 for name in _STATUS_IDENTITY}
    contract_by_release = {
        item.release_path: (index, item)
        for index, item in enumerate(PINNED_ORIGINAL_SHARDS)
    }
    shard_base: list[int] = []
    offset = 0
    for contract in PINNED_ORIGINAL_SHARDS:
        shard_base.append(offset)
        offset += contract.row_count
    for row in table.to_pylist():
        release_path = row.get("relative_path")
        pair = contract_by_release.get(release_path)
        status = row.get("source_status")
        identity = _STATUS_IDENTITY.get(status)
        source_cid = row.get("security_ir_source_cid")
        source_row = row.get("source_row_index")
        shard_row = row.get("source_shard_row_index")
        if (
            pair is None
            or identity is None
            or not isinstance(source_cid, str)
            or not _CID_RE.fullmatch(source_cid)
            or source_cid in source_cids
            or type(source_row) is not int
            or not 0 <= source_row < descriptor.row_count
            or source_rows[source_row]
            or type(shard_row) is not int
        ):
            raise HuggingFaceSourceIntegrityError(
                "original-row index identity differs"
            )
        shard_index, contract = pair
        position = shard_base[shard_index] + shard_row
        if (
            not 0 <= shard_row < contract.row_count
            or not 0 <= position < descriptor.row_count
            or positions[position]
            or source_row != position
            or row.get("source_shard_cid") != contract.cid
            or row.get("source_shard_path") != contract.source_path
            or row.get("source_dataset_id") != PINNED_SOURCE_DATASET_ID
            or row.get("source_revision") != PINNED_SOURCE_REVISION
            or row.get("schema_version") != ORIGINAL_ROW_INDEX_SCHEMA_VERSION
            or row.get("source_identity_domain") != identity[0]
            or row.get("source_identity_schema_version") != identity[1]
        ):
            raise HuggingFaceSourceIntegrityError(
                "original-row index position binding differs"
            )
        positions[position] = 1
        source_rows[source_row] = 1
        source_cids.add(source_cid)
        status_counts[status] += 1
    counts = manifest.get("counts")
    assert isinstance(counts, Mapping)
    if (
        any(value != 1 for value in positions)
        or any(value != 1 for value in source_rows)
        or status_counts["admitted"] != counts.get("admitted_rows")
        or (
            status_counts["adaptation_rejected"]
            + status_counts["publication_rejected"]
        )
        != counts.get("rejected_rows")
    ):
        raise HuggingFaceSourceIntegrityError(
            "original-row index is not a complete source-position bijection"
        )


def _validate_release_metadata(
    root: Path,
    descriptor: _ArtifactDescriptor,
    manifest: Mapping[str, Any],
    artifacts: Sequence[_ArtifactDescriptor],
    *,
    limits: HuggingFaceCompleteReleaseLimits,
) -> None:
    path = _verify_file(root, descriptor, maximum=limits.max_metadata_bytes)
    metadata = _strict_json_object(
        _bounded_bytes(path, limits.max_metadata_bytes, COMPLETE_METADATA_PATH),
        COMPLETE_METADATA_PATH,
    )
    if (
        set(metadata)
        != {"configs", "dataset_id", "derived_dataset_root", "schema_version"}
        or metadata.get("dataset_id") != manifest.get("dataset_id")
        or metadata.get("derived_dataset_root")
        != manifest.get("derived_dataset_root")
        or metadata.get("schema_version") != HF_PARQUET_SCHEMA_VERSION
    ):
        raise HuggingFaceSourceIntegrityError(
            "complete release metadata identity differs"
        )
    configs = metadata.get("configs")
    if not isinstance(configs, Mapping) or set(configs) != _VIEWER_CONFIGS:
        raise HuggingFaceSourceIntegrityError(
            "complete Viewer config inventory differs"
        )
    for config_name, value in configs.items():
        if not isinstance(value, Mapping) or set(value) != {"features", "splits"}:
            raise HuggingFaceSourceIntegrityError(
                f"Viewer config is malformed: {config_name}"
            )
        features = value.get("features")
        splits = value.get("splits")
        train = splits.get("train") if isinstance(splits, Mapping) else None
        matching = tuple(
            item for item in artifacts if item.config_name == config_name
        )
        if (
            not isinstance(features, Mapping)
            or not features
            or not isinstance(train, Mapping)
            or set(train) != {"num_bytes", "num_examples"}
            or not matching
            or train.get("num_bytes")
            != sum(item.byte_length for item in matching)
            or train.get("num_examples")
            != sum(item.row_count for item in matching)
        ):
            raise HuggingFaceSourceIntegrityError(
                f"Viewer config counts differ: {config_name}"
            )


def _exact_count(
    counts: Mapping[str, Any], name: str, expected: int
) -> None:
    if type(counts.get(name)) is not int or counts[name] != expected:
        raise HuggingFaceSourceIntegrityError(
            f"complete manifest count differs: {name}"
        )


def _validate_complete_counts(
    manifest: Mapping[str, Any],
    artifacts: Sequence[_ArtifactDescriptor],
    release_manifest: ReleaseManifest,
) -> None:
    counts = manifest.get("counts")
    graph = manifest.get("graph")
    vector = manifest.get("vector")
    runtime = manifest.get("build_runtime")
    if not all(
        isinstance(value, Mapping) for value in (counts, graph, vector, runtime)
    ):
        raise HuggingFaceSourceIntegrityError(
            "complete release count metadata is malformed"
        )
    assert isinstance(counts, Mapping)
    assert isinstance(graph, Mapping)
    assert isinstance(vector, Mapping)
    assert isinstance(runtime, Mapping)

    def rows(config: str) -> int:
        return sum(
            item.row_count for item in artifacts if item.config_name == config
        )

    _exact_count(
        counts,
        "canonical_security_ir_records",
        len(release_manifest.record_cids),
    )
    _exact_count(counts, "corpus_rows", rows("corpus"))
    _exact_count(counts, "bm25_documents", rows("bm25_documents"))
    _exact_count(counts, "bm25_posting_rows", rows("bm25_postings"))
    _exact_count(counts, "graph_nodes", rows("graph_nodes"))
    _exact_count(counts, "graph_edges", rows("graph_edges"))
    _exact_count(counts, "vector_rows", rows("vectors"))
    _exact_count(
        counts,
        "graph_data_shards",
        sum(
            1
            for item in artifacts
            if item.config_name
            in {
                "graph_edges",
                "graph_incoming_adjacency",
                "graph_nodes",
                "graph_outgoing_adjacency",
            }
        ),
    )
    graph_root = graph.get("graph_root")
    retrieval_root = vector.get("retrieval_index_root")
    cuda = runtime.get("cuda")
    if (
        graph.get("node_count") != counts["graph_nodes"]
        or graph.get("edge_count") != counts["graph_edges"]
        or not isinstance(graph_root, str)
        or not _CID_RE.fullmatch(graph_root)
        or not isinstance(retrieval_root, str)
        or not _CID_RE.fullmatch(retrieval_root)
        or vector.get("rows_sorted_by")
        != "cosine_similarity_to_shard_centroid_desc"
        or vector.get("searchable") is not True
        or vector.get("embedded_rows") != counts["vector_rows"]
        or vector.get("neutral_rows") != 0
        or vector.get("shard_count")
        != sum(1 for item in artifacts if item.config_name == "vectors")
        or type(vector.get("dimension")) is not int
        or vector["dimension"] <= 0
        or not isinstance(vector.get("model_revision"), str)
        or not _MODEL_REVISION_RE.fullmatch(vector["model_revision"])
        or not isinstance(cuda, Mapping)
        or cuda.get("cuda_required") is not True
        or cuda.get("record_count") != counts["vector_rows"]
        or cuda.get("embedding_dimension") != vector["dimension"]
        or cuda.get("model_revision") != vector["model_revision"]
    ):
        raise HuggingFaceSourceIntegrityError(
            "complete graph/vector runtime binding differs"
        )


def load_huggingface_complete_release(
    root: str | os.PathLike[str],
    pin: HuggingFaceSourcePin,
    *,
    limits: HuggingFaceCompleteReleaseLimits | None = None,
    offline: bool = True,
) -> LoadedHuggingFaceCompleteRelease:
    """Verify a complete release from only its pinned control-plane files."""

    if not isinstance(pin, HuggingFaceSourcePin):
        raise TypeError("pin must be a HuggingFaceSourcePin")
    active_limits = limits or HuggingFaceCompleteReleaseLimits()
    if not isinstance(active_limits, HuggingFaceCompleteReleaseLimits):
        raise TypeError("limits must be HuggingFaceCompleteReleaseLimits")
    if type(offline) is not bool:
        raise TypeError("offline must be boolean")
    snapshot_root = Path(root).expanduser()
    if snapshot_root.is_symlink() or not snapshot_root.is_dir():
        raise HuggingFaceSourceIntegrityError(
            "complete snapshot root must be a real directory"
        )
    snapshot_root = snapshot_root.resolve(strict=True)
    manifest_path = _safe_file(snapshot_root, "manifest.json")
    manifest_content = _bounded_bytes(
        manifest_path, active_limits.max_manifest_bytes, "manifest.json"
    )
    if hashlib.sha256(manifest_content).hexdigest() != pin.manifest_sha256:
        raise HuggingFaceSourceIntegrityError("pinned manifest digest mismatch")
    manifest = _strict_json_object(manifest_content, "manifest.json")
    if set(manifest) != _MANIFEST_FIELDS:
        raise HuggingFaceSourceIntegrityError(
            "complete manifest fields differ"
        )
    if (
        manifest.get("schema_version") != HF_RELEASE_SCHEMA_VERSION
        or manifest.get("dataset_id") != pin.dataset_id
        or manifest.get("release_root") != pin.release_root
        or manifest.get("primary_key") != "entry_cid"
        or not isinstance(manifest.get("derived_dataset_root"), str)
        or not _CID_RE.fullmatch(manifest["derived_dataset_root"])
    ):
        raise HuggingFaceSourceIntegrityError(
            "complete manifest identity differs"
        )
    artifacts = _validate_artifact_inventory(
        manifest.get("artifacts"), limits=active_limits
    )
    index_root = snapshot_root / "indexes"
    if index_root.is_symlink() or not index_root.is_dir():
        raise HuggingFaceSourceIntegrityError(
            "complete snapshot indexes path must be a real directory"
        )
    observed_indexes: set[str] = set()
    for candidate in index_root.iterdir():
        if candidate.is_symlink() or not candidate.is_file():
            raise HuggingFaceSourceIntegrityError(
                "complete snapshot indexes contain an unsafe entry"
            )
        observed_indexes.add(candidate.relative_to(snapshot_root).as_posix())
    if observed_indexes != set(_INDEX_PATHS.values()):
        raise HuggingFaceSourceIntegrityError(
            "complete snapshot index files differ from the manifest"
        )
    _validate_config_routes(manifest, artifacts)
    by_path = {item.path: item for item in artifacts}
    try:
        release_manifest = ReleaseManifest.from_dict(
            manifest["release_manifest"]
        )
    except Exception as exc:
        raise HuggingFaceSourceIntegrityError(
            "canonical complete-release manifest is invalid"
        ) from exc
    data = tuple(item for item in artifacts if _data_config(item.path))
    if (
        release_manifest.dataset_id != pin.dataset_id
        or release_manifest.parent_cids
        != (manifest["derived_dataset_root"],)
        or release_manifest.payload.get("release_root") != pin.release_root
        or release_manifest.payload.get("release_schema_version")
        != HF_RELEASE_SCHEMA_VERSION
        or release_manifest.payload.get("derived_dataset_schema_version")
        != COMPLETE_BUILD_SCHEMA_VERSION
        or release_manifest.payload.get("grants_execution_authority") is not False
        or len(release_manifest.shard_cids) != len(data)
        or set(release_manifest.shard_cids)
        != {item.content_id for item in data}
    ):
        raise HuggingFaceSourceIntegrityError(
            "canonical complete-release binding differs"
        )
    original_shards, original_rows, original_bytes = (
        _validate_original_manifest(manifest, artifacts, release_manifest)
    )
    _validate_complete_counts(manifest, artifacts, release_manifest)
    _validate_route_indexes(
        snapshot_root, artifacts, limits=active_limits
    )
    _validate_original_row_index(
        snapshot_root, artifacts, manifest, limits=active_limits
    )
    metadata_descriptor = by_path[COMPLETE_METADATA_PATH]
    _validate_release_metadata(
        snapshot_root,
        metadata_descriptor,
        manifest,
        artifacts,
        limits=active_limits,
    )
    counts = manifest["counts"]
    graph = manifest["graph"]
    vector = manifest["vector"]
    assert isinstance(counts, Mapping)
    assert isinstance(graph, Mapping)
    assert isinstance(vector, Mapping)
    receipt = HuggingFaceCompleteReleaseReceipt(
        dataset_id=pin.dataset_id,
        revision=pin.revision,
        manifest_sha256=pin.manifest_sha256,
        release_root=pin.release_root,
        derived_dataset_root=manifest["derived_dataset_root"],
        graph_root=graph["graph_root"],
        retrieval_index_root=vector["retrieval_index_root"],
        artifact_count=len(artifacts) + 1,
        control_artifact_count=len(_INDEX_PATHS) + 2,
        data_shard_count=len(data),
        index_count=len(_INDEX_PATHS),
        canonical_record_count=counts["canonical_security_ir_records"],
        corpus_row_count=counts["corpus_rows"],
        graph_node_count=counts["graph_nodes"],
        graph_edge_count=counts["graph_edges"],
        vector_row_count=counts["vector_rows"],
        original_shard_count=original_shards,
        original_row_count=original_rows,
        original_byte_count=original_bytes,
        offline=offline,
    )
    return LoadedHuggingFaceCompleteRelease(pin=pin, receipt=receipt)


@runtime_checkable
class HuggingFaceCompleteReleaseFetcher(Protocol):
    """Materialize the exact complete-release control plane."""

    def __call__(
        self, pin: HuggingFaceSourcePin, destination: Path
    ) -> None | str | os.PathLike[str]:
        ...


class HuggingFaceHubCompleteReleaseFetcher:
    """Fetch only the control plane of one immutable Hub revision."""

    def __init__(self, *, local_files_only: bool = False) -> None:
        self.local_files_only = bool(local_files_only)

    def __call__(
        self, pin: HuggingFaceSourcePin, destination: Path
    ) -> Path:
        try:
            from huggingface_hub import snapshot_download
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise HuggingFaceSourceError(
                "huggingface_hub is required for Hub complete-release fetching"
            ) from exc
        try:
            result = snapshot_download(
                repo_id=pin.dataset_id,
                revision=pin.revision,
                repo_type="dataset",
                local_dir=str(destination),
                allow_patterns=list(_CONTROL_ALLOW_PATTERNS),
                local_files_only=self.local_files_only,
            )
        except Exception as exc:  # pragma: no cover - backend/network dependent
            raise HuggingFaceSourceError(
                f"failed to fetch exact complete release {pin.logical_source}"
            ) from exc
        return Path(result)


def _copy_control_plane(source: Path, destination: Path) -> None:
    if source.is_symlink() or not source.is_dir():
        raise HuggingFaceSourceIntegrityError(
            "fetcher must return a real snapshot directory"
        )
    selected = (
        source / "manifest.json",
        source / COMPLETE_METADATA_PATH,
        *(sorted((source / "indexes").glob("*.parquet"))),
    )
    for path in selected:
        if path.is_symlink() or not path.is_file():
            raise HuggingFaceSourceIntegrityError(
                "fetcher returned an incomplete control plane"
            )
        relative = path.relative_to(source)
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target, follow_symlinks=False)


class HuggingFaceCompleteReleaseCache:
    """Revision-preserving cache that never stores mirrored source bodies."""

    _MARKER = ".cvefixes-hf-complete-source.json"

    def __init__(
        self,
        root: str | os.PathLike[str],
        *,
        fetcher: HuggingFaceCompleteReleaseFetcher | None = None,
        limits: HuggingFaceCompleteReleaseLimits | None = None,
    ) -> None:
        root_path = Path(root).expanduser()
        try:
            root_path.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise HuggingFaceSourceIntegrityError(
                "complete-release cache root must be a real directory"
            ) from exc
        if root_path.is_symlink() or not root_path.is_dir():
            raise HuggingFaceSourceIntegrityError(
                "complete-release cache root must be a real directory"
            )
        self.root = root_path.resolve(strict=True)
        self.fetcher = fetcher
        self.limits = limits or HuggingFaceCompleteReleaseLimits()
        if not isinstance(self.limits, HuggingFaceCompleteReleaseLimits):
            raise TypeError("limits must be HuggingFaceCompleteReleaseLimits")
        self.snapshots = self.root / "snapshots"
        self.snapshots.mkdir(exist_ok=True)
        if self.snapshots.is_symlink() or not self.snapshots.is_dir():
            raise HuggingFaceSourceIntegrityError(
                "complete-release snapshots path must be a real directory"
            )

    def path_for(self, pin: HuggingFaceSourcePin) -> Path:
        if not isinstance(pin, HuggingFaceSourcePin):
            raise TypeError("pin must be a HuggingFaceSourcePin")
        return self.snapshots / pin.cache_key

    def load(
        self, pin: HuggingFaceSourcePin
    ) -> LoadedHuggingFaceCompleteRelease:
        path = self.path_for(pin)
        if not path.exists():
            raise HuggingFaceSourceCacheMiss(
                f"offline complete-release cache miss for {pin.logical_source}"
            )
        self._verify_marker(path, pin)
        return load_huggingface_complete_release(
            path, pin, limits=self.limits, offline=True
        )

    def materialize(
        self, pin: HuggingFaceSourcePin
    ) -> LoadedHuggingFaceCompleteRelease:
        path = self.path_for(pin)
        if path.exists():
            return self.load(pin)
        if self.fetcher is None:
            raise HuggingFaceSourceCacheMiss(
                f"offline complete-release cache miss for {pin.logical_source}"
            )
        temporary = Path(
            tempfile.mkdtemp(prefix=f".{pin.cache_key}.", dir=self.snapshots)
        )
        try:
            returned = self.fetcher(pin, temporary)
            if returned is not None:
                returned_path = Path(returned).expanduser().resolve(strict=True)
                if returned_path != temporary.resolve(strict=True):
                    _copy_control_plane(returned_path, temporary)
            loaded = load_huggingface_complete_release(
                temporary, pin, limits=self.limits, offline=False
            )
            marker = {
                "pin": pin.to_dict(),
                "schema_version": HF_COMPLETE_SOURCE_CACHE_SCHEMA_VERSION,
            }
            (temporary / self._MARKER).write_bytes(canonical_json_bytes(marker))
            try:
                temporary.replace(path)
            except FileExistsError:
                shutil.rmtree(temporary)
                return self.load(pin)
            return loaded
        except Exception:
            if temporary.exists():
                shutil.rmtree(temporary)
            raise

    def _verify_marker(self, path: Path, pin: HuggingFaceSourcePin) -> None:
        if path.is_symlink() or not path.is_dir():
            raise HuggingFaceSourceIntegrityError(
                "complete-release cache entry must be a real directory"
            )
        root = path.resolve(strict=True)
        marker = _strict_json_object(
            _bounded_bytes(
                _safe_file(root, self._MARKER),
                self.limits.max_metadata_bytes,
                "complete-release cache marker",
            ),
            "complete-release cache marker",
        )
        if (
            set(marker) != {"pin", "schema_version"}
            or marker.get("schema_version")
            != HF_COMPLETE_SOURCE_CACHE_SCHEMA_VERSION
        ):
            raise HuggingFaceSourceIntegrityError(
                "complete-release cache marker schema differs"
            )
        try:
            cached_pin = HuggingFaceSourcePin.from_dict(marker["pin"])
        except Exception as exc:
            raise HuggingFaceSourceIntegrityError(
                "complete-release cache marker pin is invalid"
            ) from exc
        if cached_pin != pin:
            raise HuggingFaceSourceIntegrityError(
                "complete-release cache pin differs"
            )


__all__ = [
    "COMPLETE_BUILD_SCHEMA_VERSION",
    "COMPLETE_METADATA_PATH",
    "DERIVED_SECURITY_IR_PROFILE",
    "HF_COMPLETE_SOURCE_CACHE_SCHEMA_VERSION",
    "HF_COMPLETE_SOURCE_SCHEMA_VERSION",
    "HuggingFaceCompleteReleaseCache",
    "HuggingFaceCompleteReleaseFetcher",
    "HuggingFaceCompleteReleaseLimits",
    "HuggingFaceCompleteReleaseReceipt",
    "HuggingFaceHubCompleteReleaseFetcher",
    "LoadedHuggingFaceCompleteRelease",
    "ORIGINAL_MIRROR_PROFILE",
    "ORIGINAL_ROW_INDEX_SCHEMA_VERSION",
    "PINNED_ORIGINAL_SHARDS",
    "PINNED_SOURCE_DATASET_ID",
    "PINNED_SOURCE_PROFILE_SHA256",
    "PINNED_SOURCE_REVISION",
    "load_huggingface_complete_release",
]
