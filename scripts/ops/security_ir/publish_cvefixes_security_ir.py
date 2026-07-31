#!/usr/bin/env python3
"""Safely publish and verify a staged CVEfixes Security IR Hub release.

The command is deliberately dry-run by default.  ``--execute`` reads a token
from the named environment variable, authenticates it, searches the bounded
Hub history for the release tuple, and uploads only when that tuple is absent.
No token is accepted on the command line or included in output, exceptions,
commit metadata, or receipts.

A publication receipt is only a *proposal*: it cannot grant completion or
execution authority.  It is produced after the immutable Hub commit, every
remote artifact, and the Dataset Viewer shards/features have been verified.
"""

from __future__ import annotations

import argparse
import base64
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import sys
import time
from typing import Any, Final, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen


DEFAULT_TARGET_REPO: Final = "Publicus/cvefixes-security-ir-graphrag"
PUBLICATION_RECEIPT_VERSION: Final = (
    "cvefixes-security-ir-publication-receipt/v1"
)
RELEASE_SCHEMA_VERSION: Final = "cvefixes-huggingface-release/v1"
PARQUET_SCHEMA_VERSION: Final = "cvefixes-huggingface-parquet/v1"
# Complete releases use README config declarations, like SkillCenter.  The
# legacy name remains readable only for old, non-complete release layouts.
COMPLETE_RELEASE_METADATA_PATH: Final = "release-metadata.json"
LEGACY_RELEASE_METADATA_PATH: Final = "dataset_infos.json"
ORIGINAL_MIRROR_PROFILE: Final = "cvefixes-byte-preserving-mirror/v1"
ORIGINAL_ROW_INDEX_SCHEMA_VERSION: Final = (
    "cvefixes-hf-original-row-index/v1"
)
PINNED_SOURCE_DATASET_ID: Final = "hitoshura25/cvefixes"
PINNED_SOURCE_REVISION: Final = "d4f5c4ea65329d9ccbb8a3b3149e5d06eda5edb2"
PINNED_SOURCE_PROFILE_SHA256: Final = (
    "163e267f9ffd9b5d0193dc26014b775c8ebb7dc804772473ef8a6aa8bd3eb3d1"
)


@dataclass(frozen=True, slots=True)
class OriginalShardContract:
    release_path: str
    source_path: str
    sha256: str
    size_bytes: int
    row_count: int


PINNED_ORIGINAL_SHARDS: Final[tuple[OriginalShardContract, ...]] = (
    OriginalShardContract(
        release_path="data/original/part-000000.parquet",
        source_path="data/train-00000-of-00003.parquet",
        sha256="2e25e84e85e1560d41acacbfc7eb359349f5417bc9bf31318cdf0c4aafccb7d1",
        size_bytes=211_599_861,
        row_count=4_329,
    ),
    OriginalShardContract(
        release_path="data/original/part-000001.parquet",
        source_path="data/train-00001-of-00003.parquet",
        sha256="3a4251f39955f95c232b4aea98daa59bbe0c7b5e27c9189c1b09f64b960a35d7",
        size_bytes=428_366_432,
        row_count=4_329,
    ),
    OriginalShardContract(
        release_path="data/original/part-000002.parquet",
        source_path="data/train-00002-of-00003.parquet",
        sha256="55488d569ac978ea077be643233355f43458d636d04ad3ae1cb973895b02a3ac",
        size_bytes=580_353_186,
        row_count=4_329,
    ),
)
EXPECTED_COLUMNS: Final[tuple[str, ...]] = (
    "record_id",
    "record_type",
    "authority",
    "source_cids",
    "parent_cids",
    "config_cid",
    "record_json",
)
CORPUS_COLUMNS: Final[tuple[str, ...]] = (
    "document_index",
    "entry_cid",
    "node_cid",
    "title",
    "text",
    "partition",
    "shard_key",
    "kind",
    "authority",
    "source_cids",
    "cwes",
    "languages",
    "code_facts",
    "actions",
    "effects",
    "policies",
    "graph_node",
    "grants_execution_authority",
    "text_sha256",
    "schema_version",
)
BM25_DOCUMENT_COLUMNS: Final[tuple[str, ...]] = (
    "authority",
    "body_length",
    "body_sha256",
    "document_index",
    "document_length",
    "entry_cid",
    "record_type",
    "schema_version",
    "title",
    "title_length",
    "token_input_sha256",
)
BM25_POSTING_COLUMNS: Final[tuple[str, ...]] = (
    "body_frequencies",
    "corpus_frequency",
    "document_frequency",
    "document_indices",
    "document_lengths",
    "idf",
    "posting_chunk_count",
    "posting_chunk_index",
    "schema_version",
    "term",
    "title_frequencies",
)
GRAPH_NODE_COLUMNS: Final[tuple[str, ...]] = (
    "node_cid",
    "node_type",
    "entry_cid",
    "label",
    "properties_json",
    "schema_version",
)
GRAPH_EDGE_COLUMNS: Final[tuple[str, ...]] = (
    "edge_cid",
    "edge_type",
    "source_cid",
    "target_cid",
    "retrieval_method",
    "score",
    "query_terms_json",
    "properties_json",
    "schema_version",
)
GRAPH_ADJACENCY_COLUMNS: Final[tuple[str, ...]] = (
    "direction",
    "edge_cids",
    "edge_types",
    "neighbor_cids",
    "neighbor_count",
    "neighbor_node_types",
    "node_cid",
    "page_count",
    "page_index",
    "retrieval_methods",
    "schema_version",
    "scores",
    "total_neighbor_count",
)
VECTOR_COLUMNS: Final[tuple[str, ...]] = (
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
META_INDEX_COLUMNS: Final[tuple[str, ...]] = (
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
BM25_KEYWORD_META_COLUMNS: Final[tuple[str, ...]] = (
    *META_INDEX_COLUMNS,
    "posting_count",
    "term_count",
    "token_instance_count",
)
VECTOR_META_COLUMNS: Final[tuple[str, ...]] = (
    *META_INDEX_COLUMNS,
    "centroid",
    "centroid_min_score",
    "centroid_shard_count",
    "chunk_in_cluster",
    "cluster_id",
    "dimension",
    "model_name",
    "shard_centroid",
)
GRAPH_ADJACENCY_META_COLUMNS: Final[tuple[str, ...]] = (
    *META_INDEX_COLUMNS,
    "adjacency_count",
    "direction",
    "first_page_index",
    "last_page_index",
    "node_count",
)
ORIGINAL_DATA_COLUMNS: Final[tuple[str, ...]] = (
    "cve_id",
    "hash",
    "repo_url",
    "cve_description",
    "cvss2_base_score",
    "cvss3_base_score",
    "published_date",
    "severity",
    "cwe_id",
    "cwe_name",
    "cwe_description",
    "commit_message",
    "commit_date",
    "version_tag",
    "repo_total_files",
    "repo_total_commits",
    "file_paths",
    "language",
    "diff_stats",
    "diff_with_context",
    "vulnerable_code",
    "fixed_code",
    "security_keywords",
)
ORIGINAL_ROW_INDEX_COLUMNS: Final[tuple[str, ...]] = (
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
META_INDEX_CONFIGS: Final[Mapping[str, str]] = {
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
COMPLETE_DATA_CONFIG_PATHS: Final[Mapping[str, str]] = {
    "corpus": "data/corpus/",
    "bm25_documents": "data/bm25/documents/",
    "bm25_postings": "data/bm25/postings/",
    "graph_nodes": "data/graph/nodes/",
    "graph_edges": "data/graph/edges/",
    "graph_outgoing_adjacency": "data/graph/adjacency/outgoing/",
    "graph_incoming_adjacency": "data/graph/adjacency/incoming/",
    "original_data": "data/original/",
    "vectors": "data/vectors/",
}
COMPLETE_INDEX_PATHS: Final[Mapping[str, str]] = {
    f"indexes/{name}.parquet": config
    for name, config in META_INDEX_CONFIGS.items()
}
COMPLETE_VIEWER_CONFIGS: Final[frozenset[str]] = frozenset(
    {
        *COMPLETE_DATA_CONFIG_PATHS,
        "corpus_chunk_index",
        "bm25_keyword_index",
        "vector_meta_index",
        "graph_outgoing_adjacency_index",
        "graph_incoming_adjacency_index",
        "original_row_index",
    }
)
_HIDDEN_INDEX_CONFIGS: Final[frozenset[str]] = frozenset(
    {
        "bm25_document_chunk_index",
        "graph_edge_chunk_index",
        "graph_node_chunk_index",
    }
)
_COMPLETE_INDEX_FAMILY: Final[Mapping[str, str]] = {
    "indexes/corpus_chunks.parquet": "corpus",
    "indexes/bm25_document_chunks.parquet": "bm25_documents",
    "indexes/bm25_keyword_shards.parquet": "bm25_postings",
    "indexes/graph_node_chunks.parquet": "graph_nodes",
    "indexes/graph_edge_chunks.parquet": "graph_edges",
    "indexes/graph_outgoing_adjacency.parquet": (
        "graph_outgoing_adjacency"
    ),
    "indexes/graph_incoming_adjacency.parquet": (
        "graph_incoming_adjacency"
    ),
    "indexes/original_rows.parquet": "original_data",
    "indexes/vector_chunks.parquet": "vectors",
}
_CONFIG_COLUMNS: Final[Mapping[str, tuple[str, ...]]] = {
    "corpus": CORPUS_COLUMNS,
    "bm25_documents": BM25_DOCUMENT_COLUMNS,
    "bm25_postings": BM25_POSTING_COLUMNS,
    "graph_nodes": GRAPH_NODE_COLUMNS,
    "graph_edges": GRAPH_EDGE_COLUMNS,
    "graph_outgoing_adjacency": GRAPH_ADJACENCY_COLUMNS,
    "graph_incoming_adjacency": GRAPH_ADJACENCY_COLUMNS,
    "original_data": ORIGINAL_DATA_COLUMNS,
    "vectors": VECTOR_COLUMNS,
    "corpus_chunk_index": META_INDEX_COLUMNS,
    "bm25_document_chunk_index": META_INDEX_COLUMNS,
    "bm25_keyword_index": BM25_KEYWORD_META_COLUMNS,
    "graph_node_chunk_index": META_INDEX_COLUMNS,
    "graph_edge_chunk_index": META_INDEX_COLUMNS,
    "graph_outgoing_adjacency_index": GRAPH_ADJACENCY_META_COLUMNS,
    "graph_incoming_adjacency_index": GRAPH_ADJACENCY_META_COLUMNS,
    "original_row_index": ORIGINAL_ROW_INDEX_COLUMNS,
    "vector_meta_index": VECTOR_META_COLUMNS,
}
_CONFIG_SCHEMA_VERSIONS: Final[Mapping[str, str]] = {
    "corpus": "cvefixes-hf-corpus/v1",
    "bm25_documents": "cvefixes-hf-bm25-document/v1",
    "bm25_postings": "cvefixes-hf-bm25-posting/v1",
    "graph_nodes": "cvefixes-hf-graph-node/v1",
    "graph_edges": "cvefixes-hf-graph-edge/v1",
    "graph_outgoing_adjacency": "cvefixes-hf-graph-adjacency/v1",
    "graph_incoming_adjacency": "cvefixes-hf-graph-adjacency/v1",
    "vectors": "cvefixes-hf-vector-chunk/v1",
    **{
        config: "cvefixes-hf-shard-meta/v1"
        for config in META_INDEX_CONFIGS.values()
        if config != "original_row_index"
    },
    "original_row_index": ORIGINAL_ROW_INDEX_SCHEMA_VERSION,
}
_DATA_KEY_COLUMNS: Final[Mapping[str, str]] = {
    "corpus": "entry_cid",
    "bm25_documents": "entry_cid",
    "bm25_postings": "term",
    "graph_nodes": "node_cid",
    "graph_edges": "edge_cid",
    "graph_outgoing_adjacency": "node_cid",
    "graph_incoming_adjacency": "node_cid",
    "original_data": "cve_id",
    "vectors": "entry_cid",
}
MAX_MANIFEST_BYTES: Final = 8 * 1024 * 1024
MAX_VIEWER_RESPONSE_BYTES: Final = 16 * 1024 * 1024
MAX_ARTIFACT_BYTES: Final = 128 * 1024 * 1024
MAX_ARTIFACTS: Final = 2_048
MAX_HISTORY_COMMITS: Final = 100
_MANIFEST_OPTIONAL_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "indexes",
        "counts",
        "bm25",
        "vector",
        "graph",
        "parquet",
        "configs",
        "build_runtime",
        "primary_key",
    }
)

_DATASET_ID_RE = re.compile(
    r"[A-Za-z0-9][A-Za-z0-9._-]{0,95}/"
    r"[A-Za-z0-9][A-Za-z0-9._-]{0,95}"
)
_CID_RE = re.compile(r"b[a-z2-7]{58}")
_SHA256_RE = re.compile(r"[0-9a-f]{64}")
_CVE_ID_RE = re.compile(r"CVE-[0-9]{4}-[0-9]{4,}")
_GIT_HASH_RE = re.compile(r"[0-9a-f]{40}")
_COMMIT_RE = re.compile(r"[0-9a-f]{40,64}")
_CONFIG_RE = re.compile(r"[a-z][a-z0-9_]{0,63}")
_ENV_RE = re.compile(r"[A-Z][A-Z0-9_]{0,127}")
_SECRET_VALUE_RE = re.compile(
    r"(?:-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----|"
    r"(?<![A-Za-z0-9])(?:gh[pousr]_[A-Za-z0-9]{30,255}|"
    r"github_pat_[A-Za-z0-9_]{40,255}|"
    r"hf_[A-Za-z0-9]{20,255}|"
    r"sk-(?:proj-|svcacct-)?[A-Za-z0-9_-]{20,})(?![A-Za-z0-9]))"
)
_SECRET_KEYS: Final[frozenset[str]] = frozenset(
    {
        "access_token",
        "api_key",
        "authorization",
        "credential",
        "credentials",
        "hf_token",
        "password",
        "private_key",
        "secret",
        "token",
    }
)
_JSON_MEDIA_TYPES: Final[frozenset[str]] = frozenset(
    {"application/json", "text/markdown; charset=utf-8"}
)


class PublicationError(RuntimeError):
    """Base class for safe, user-facing publication failures."""


class LocalReleaseError(PublicationError):
    """The staged release is malformed, unsafe, or internally inconsistent."""


class AuthenticationError(PublicationError):
    """The explicitly supplied environment credential is absent or rejected."""


class RemoteVerificationError(PublicationError):
    """The immutable Hub data or Dataset Viewer response failed closed."""


class ViewerNotReadyError(RemoteVerificationError):
    """The Dataset Viewer has not finished processing the current release."""


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=True, allow_nan=False, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")


def _object(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise LocalReleaseError(f"{label} must be a JSON object")
    return value


def _bounded_bytes(path: Path, *, maximum: int, label: str) -> bytes:
    try:
        stat = path.stat()
    except OSError as exc:
        raise LocalReleaseError(f"cannot inspect {label}") from exc
    if not path.is_file() or path.is_symlink():
        raise LocalReleaseError(f"{label} must be a regular file")
    if stat.st_size > maximum:
        raise LocalReleaseError(f"{label} exceeds its byte limit")
    try:
        return path.read_bytes()
    except OSError as exc:
        raise LocalReleaseError(f"cannot read {label}") from exc


def _json_bytes(content: bytes, label: str) -> Mapping[str, Any]:
    try:
        value = json.loads(content)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise LocalReleaseError(f"{label} is not valid UTF-8 JSON") from exc
    return _object(value, label)


def _raw_sha256_cid(digest: bytes) -> str:
    """Return CIDv1(raw, sha2-256) for an already-computed SHA-256 digest."""

    if not isinstance(digest, bytes) or len(digest) != 32:
        raise LocalReleaseError("raw CID digest must be SHA-256")
    payload = bytes((0x01, 0x55, 0x12, 0x20)) + digest
    encoded = base64.b32encode(payload).decode("ascii").lower().rstrip("=")
    return f"b{encoded}"


def _original_contract(path: str) -> OriginalShardContract | None:
    return next(
        (
            contract
            for contract in PINNED_ORIGINAL_SHARDS
            if contract.release_path == path
        ),
        None,
    )


def _artifact_byte_limit(path: str) -> int:
    contract = _original_contract(path)
    return contract.size_bytes if contract is not None else MAX_ARTIFACT_BYTES


def _stream_file_sha256(
    path: Path,
    *,
    maximum: int,
    label: str,
) -> tuple[int, bytes]:
    try:
        stat = path.stat()
    except OSError as exc:
        raise LocalReleaseError(f"cannot inspect {label}") from exc
    if not path.is_file() or path.is_symlink():
        raise LocalReleaseError(f"{label} must be a regular file")
    if stat.st_size > maximum:
        raise LocalReleaseError(f"{label} exceeds its byte limit")
    digest = hashlib.sha256()
    observed = 0
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
                observed += len(chunk)
                if observed > maximum:
                    raise LocalReleaseError(f"{label} exceeds its byte limit")
                digest.update(chunk)
    except LocalReleaseError:
        raise
    except OSError as exc:
        raise LocalReleaseError(f"cannot read {label}") from exc
    if observed != stat.st_size:
        raise LocalReleaseError(f"{label} changed while being read")
    return observed, digest.digest()


def _complete_data_config(path: str) -> str | None:
    for config_name, prefix in COMPLETE_DATA_CONFIG_PATHS.items():
        if path.startswith(prefix) and re.fullmatch(
            r"part-\d{6}\.parquet", path[len(prefix) :]
        ):
            return config_name
    return None


def _expected_artifact_config(path: str) -> str | None:
    complete = _complete_data_config(path)
    if complete is not None:
        return complete
    if path in COMPLETE_INDEX_PATHS:
        return COMPLETE_INDEX_PATHS[path]
    parsed = PurePosixPath(path)
    if (
        len(parsed.parts) == 3
        and parsed.parts[0] == "data"
        and _CONFIG_RE.fullmatch(parsed.parts[1])
        and re.fullmatch(
            r"train-\d{5}-of-\d{5}\.parquet", parsed.parts[2]
        )
    ):
        return parsed.parts[1]
    return None


def _safe_artifact_path(value: Any) -> str:
    if not isinstance(value, str) or not value or len(value) > 512:
        raise LocalReleaseError("artifact path must be bounded text")
    parsed = PurePosixPath(value)
    if (
        parsed.is_absolute()
        or value != parsed.as_posix()
        or "\\" in value
        or any(part in {"", ".", ".."} for part in parsed.parts)
    ):
        raise LocalReleaseError("artifact path is unsafe")
    if len(parsed.parts) == 1:
        if value not in {
            "README.md",
            COMPLETE_RELEASE_METADATA_PATH,
            LEGACY_RELEASE_METADATA_PATH,
            "evaluation-report.json",
        }:
            raise LocalReleaseError("unexpected top-level release artifact")
    elif _expected_artifact_config(value) is None:
        raise LocalReleaseError("unexpected release artifact path")
    return value


def _safe_public_value(value: Any, *, location: str = "$") -> None:
    if isinstance(value, Mapping):
        for raw_key, item in value.items():
            if not isinstance(raw_key, str):
                raise LocalReleaseError(f"non-string key at {location}")
            if raw_key.casefold() in _SECRET_KEYS:
                raise LocalReleaseError(
                    f"credential-like field is forbidden at {location}"
                )
            _safe_public_value(item, location=f"{location}.{raw_key}")
        return
    if isinstance(value, Sequence) and not isinstance(
        value, (str, bytes, bytearray)
    ):
        for index, item in enumerate(value):
            _safe_public_value(item, location=f"{location}[{index}]")
        return
    if isinstance(value, str) and _SECRET_VALUE_RE.search(value):
        raise LocalReleaseError(f"secret-like value is forbidden at {location}")


@dataclass(frozen=True, slots=True)
class ArtifactDescriptor:
    path: str
    media_type: str
    byte_length: int
    sha256: str
    content_id: str
    config_name: str = ""
    row_count: int = 0

    @classmethod
    def from_dict(cls, value: Any) -> "ArtifactDescriptor":
        item = _object(value, "artifact descriptor")
        path = _safe_artifact_path(item.get("path"))
        parquet = path.endswith(".parquet")
        required = {
            "byte_length",
            "content_id",
            "media_type",
            "path",
            "sha256",
        }
        if parquet:
            required |= {"config_name", "row_count"}
        if set(item) != required:
            raise LocalReleaseError("artifact descriptor fields are not canonical")
        byte_length = item["byte_length"]
        row_count = item.get("row_count", 0)
        media_type = item["media_type"]
        sha256 = item["sha256"]
        content_id = item["content_id"]
        config_name = item.get("config_name", "")
        original_contract = _original_contract(path)
        if (
            type(byte_length) is not int
            or byte_length < 0
            or byte_length > _artifact_byte_limit(path)
        ):
            raise LocalReleaseError("artifact byte_length is invalid")
        if not isinstance(media_type, str) or not media_type or len(media_type) > 128:
            raise LocalReleaseError("artifact media_type is invalid")
        if not isinstance(sha256, str) or not _SHA256_RE.fullmatch(sha256):
            raise LocalReleaseError("artifact SHA-256 is invalid")
        if not isinstance(content_id, str) or not _CID_RE.fullmatch(content_id):
            raise LocalReleaseError("artifact content ID is invalid")
        if parquet:
            expected_config = _expected_artifact_config(path)
            if (
                media_type != "application/vnd.apache.parquet"
                or not isinstance(config_name, str)
                or not _CONFIG_RE.fullmatch(config_name)
                or expected_config != config_name
                or type(row_count) is not int
                or row_count <= 0
            ):
                raise LocalReleaseError("Parquet descriptor metadata is invalid")
            if original_contract is not None and (
                config_name != "original_data"
                or byte_length != original_contract.size_bytes
                or row_count != original_contract.row_count
                or sha256 != original_contract.sha256
                or content_id
                != _raw_sha256_cid(bytes.fromhex(original_contract.sha256))
            ):
                raise LocalReleaseError(
                    "pinned original-data descriptor is invalid"
                )
        elif media_type not in _JSON_MEDIA_TYPES:
            raise LocalReleaseError("release artifact media type is unexpected")
        return cls(
            path=path,
            media_type=media_type,
            byte_length=byte_length,
            sha256=sha256,
            content_id=content_id,
            config_name=config_name,
            row_count=row_count,
        )

    def receipt_dict(self) -> dict[str, Any]:
        return {
            "byte_length": self.byte_length,
            "config_name": self.config_name,
            "content_id": self.content_id,
            "path": self.path,
            "row_count": self.row_count,
            "sha256": self.sha256,
        }


@dataclass(frozen=True, slots=True)
class LocalRelease:
    directory: Path
    dataset_id: str
    source_dataset_id: str
    source_revision: str
    release_root: str
    manifest_bytes: bytes
    manifest_sha256: str
    artifacts: tuple[ArtifactDescriptor, ...]
    config_names: tuple[str, ...]
    config_shard_counts: tuple[tuple[str, int], ...]
    complete_layout: bool = False
    original_data_acknowledgement_required: bool = False

    @property
    def parquet_artifacts(self) -> tuple[ArtifactDescriptor, ...]:
        return tuple(item for item in self.artifacts if item.config_name)

    def columns_for_config(self, config_name: str) -> tuple[str, ...]:
        paths = {
            item.path
            for item in self.parquet_artifacts
            if item.config_name == config_name
        }
        if not paths:
            raise LocalReleaseError("dataset config has no Parquet artifacts")
        is_meta = {path.startswith("indexes/") for path in paths}
        if len(is_meta) != 1:
            raise LocalReleaseError("dataset config mixes data and meta-index shards")
        expected = _CONFIG_COLUMNS.get(config_name)
        if expected is not None:
            return expected
        return META_INDEX_COLUMNS if is_meta == {True} else EXPECTED_COLUMNS

    @property
    def idempotency_key(self) -> str:
        digest = hashlib.sha256(
            _canonical_json(
                {
                    "release_root": self.release_root,
                    "source_revision": self.source_revision,
                    "target_repo": self.dataset_id,
                }
            )
        ).hexdigest()
        return f"cvefixes-publication:{digest}"


def _field_kind(config_name: str, name: str) -> str:
    list_strings = {
        "source_cids",
        "cwes",
        "languages",
        "code_facts",
        "actions",
        "effects",
        "policies",
        "edge_cids",
        "edge_types",
        "neighbor_cids",
        "neighbor_node_types",
        "retrieval_methods",
        "file_paths",
        "security_keywords",
    }
    list_int32 = {
        "body_frequencies",
        "document_indices",
        "document_lengths",
        "title_frequencies",
    }
    int32 = {
        "body_length",
        "document_index",
        "title_length",
        "document_length",
        "posting_chunk_count",
        "posting_chunk_index",
        "document_frequency",
        "neighbor_count",
        "page_count",
        "page_index",
        "cluster_id",
        "corpus_chunk_id",
        "corpus_row_offset",
        "centroid_shard_count",
        "chunk_in_cluster",
        "dimension",
        "shard_id",
        "term_count",
        "first_page_index",
        "last_page_index",
        "node_count",
        "source_row_index",
        "source_shard_row_index",
    }
    int64 = {
        "corpus_frequency",
        "faiss_id",
        "total_neighbor_count",
        "end_document_index",
        "row_count",
        "size_bytes",
        "start_document_index",
        "posting_count",
        "token_instance_count",
        "adjacency_count",
        "repo_total_files",
        "repo_total_commits",
    }
    bools = {
        "graph_node",
        "grants_execution_authority",
        "has_embedding",
    }
    large_strings = {"text", "properties_json", "query_terms_json"}
    float64 = {"cvss2_base_score", "cvss3_base_score", "idf", "score"}
    float32 = {"centroid_min_score"}
    list_float64 = {"scores"}
    list_float32 = {"centroid", "shard_centroid"}
    if config_name == "vectors" and name == "embedding":
        return "fixed_or_list_float32"
    if name in list_strings:
        return "list_string"
    if name in list_int32:
        return "list_int32"
    if name in int32:
        # Corpus and BM25 document indices are intentionally compact int32;
        # vector document indices are int64 to match their persisted index.
        if name == "document_index" and config_name == "vectors":
            return "int64"
        return "int32"
    if name in int64:
        return "int64"
    if name in bools:
        return "bool"
    if name in large_strings:
        return "large_string"
    if name in float64:
        return "float64"
    if name in float32:
        return "float32"
    if name in list_float64:
        return "list_float64"
    if name in list_float32:
        return "list_float32"
    return "string"


def _validate_field_types(schema: Any, config_name: str, pa: Any) -> None:
    for field in schema:
        kind = _field_kind(config_name, field.name)
        valid = {
            "string": pa.types.is_string(field.type),
            "large_string": pa.types.is_large_string(field.type),
            "int32": pa.types.is_int32(field.type),
            "int64": pa.types.is_int64(field.type),
            "float32": pa.types.is_float32(field.type),
            "float64": pa.types.is_float64(field.type),
            "bool": pa.types.is_boolean(field.type),
            "list_string": (
                pa.types.is_list(field.type)
                and pa.types.is_string(field.type.value_type)
            ),
            "list_int32": (
                pa.types.is_list(field.type)
                and pa.types.is_int32(field.type.value_type)
            ),
            "list_float32": (
                pa.types.is_list(field.type)
                and pa.types.is_float32(field.type.value_type)
            ),
            "list_float64": (
                pa.types.is_list(field.type)
                and pa.types.is_float64(field.type.value_type)
            ),
            "fixed_or_list_float32": (
                (
                    pa.types.is_list(field.type)
                    or pa.types.is_fixed_size_list(field.type)
                )
                and pa.types.is_float32(field.type.value_type)
            ),
        }[kind]
        if not valid:
            raise LocalReleaseError(
                f"Parquet field type mismatch: {config_name}.{field.name}"
            )


def _validate_parquet(
    path: Path,
    descriptor: ArtifactDescriptor,
    *,
    complete_layout: bool = False,
) -> None:
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ImportError as exc:  # pragma: no cover - release dependency in CI
        raise LocalReleaseError(
            "pyarrow is required to validate release shards"
        ) from exc
    try:
        parquet = pq.ParquetFile(path)
        schema = parquet.schema_arrow
    except Exception as exc:
        raise LocalReleaseError(
            f"Parquet shard is unreadable: {descriptor.path}"
        ) from exc
    expected_columns = _CONFIG_COLUMNS.get(descriptor.config_name)
    if expected_columns is None:
        expected_columns = (
            META_INDEX_COLUMNS
            if descriptor.path.startswith("indexes/")
            else EXPECTED_COLUMNS
        )
    if tuple(schema.names) != expected_columns:
        raise LocalReleaseError(
            f"Parquet schema mismatch: {descriptor.path}"
        )
    if descriptor.config_name in _CONFIG_COLUMNS:
        _validate_field_types(schema, descriptor.config_name, pa)
    if complete_layout:
        compressions = {
            parquet.metadata.row_group(group).column(column).compression
            for group in range(parquet.num_row_groups)
            for column in range(
                parquet.metadata.row_group(group).num_columns
            )
        }
        original_data = descriptor.config_name == "original_data"
        expected_compression = {"SNAPPY"} if original_data else {"ZSTD"}
        if compressions != expected_compression:
            raise LocalReleaseError(
                "complete-layout Parquet compression mismatch: "
                f"{descriptor.path}"
            )
        if original_data:
            if b"schema_version" in (schema.metadata or {}):
                raise LocalReleaseError(
                    "original-data Parquet must retain its unversioned schema"
                )
        else:
            expected_version = _CONFIG_SCHEMA_VERSIONS[descriptor.config_name]
            metadata = schema.metadata or {}
            if metadata.get(b"schema_version") != expected_version.encode("ascii"):
                raise LocalReleaseError(
                    f"Parquet schema version mismatch: {descriptor.path}"
                )
            if (
                descriptor.config_name == "original_row_index"
                and metadata.get(b"primary_key")
                != b"security_ir_source_cid"
            ):
                raise LocalReleaseError(
                    "original-row index primary key is invalid"
                )
            try:
                versions = set(
                    parquet.read(columns=["schema_version"])[
                        "schema_version"
                    ].to_pylist()
                )
            except Exception as exc:
                raise LocalReleaseError(
                    f"cannot validate schema-version rows: {descriptor.path}"
                ) from exc
            if versions != {expected_version}:
                raise LocalReleaseError(
                    f"Parquet row schema version mismatch: {descriptor.path}"
                )
    if descriptor.path.startswith("indexes/"):
        if parquet.metadata.num_rows != descriptor.row_count:
            raise LocalReleaseError("Parquet row count does not match manifest")
        return
    if _complete_data_config(descriptor.path) is not None:
        if parquet.metadata.num_rows != descriptor.row_count:
            raise LocalReleaseError("Parquet row count does not match manifest")
        return
    scalar_columns = {
        "record_id",
        "record_type",
        "authority",
        "config_cid",
        "record_json",
    }
    for field in schema:
        if field.name in scalar_columns and not pa.types.is_string(field.type):
            raise LocalReleaseError("Parquet scalar columns must be strings")
        if field.name in {"source_cids", "parent_cids"} and not (
            pa.types.is_list(field.type)
            and pa.types.is_string(field.type.value_type)
        ):
            raise LocalReleaseError("Parquet lineage columns must be string lists")
    if parquet.metadata.num_rows != descriptor.row_count:
        raise LocalReleaseError("Parquet row count does not match manifest")
    rows_seen = 0
    try:
        batches = parquet.iter_batches(
            batch_size=1_024,
            columns=("record_id", "record_type", "record_json"),
        )
        for batch in batches:
            for row in batch.to_pylist():
                record_id = row["record_id"]
                record_type = row["record_type"]
                record_json = row["record_json"]
                if (
                    not isinstance(record_id, str)
                    or not isinstance(record_type, str)
                    or record_type != descriptor.config_name
                    or not isinstance(record_json, str)
                ):
                    raise LocalReleaseError(
                        "Parquet row identity columns are invalid"
                    )
                record = _json_bytes(
                    record_json.encode("utf-8"), "Parquet record_json"
                )
                _safe_public_value(record, location="$.record_json")
                if (
                    record.get("record_id") != record_id
                    or record.get("record_type") != record_type
                    or _canonical_json(record).decode("utf-8") != record_json
                ):
                    raise LocalReleaseError(
                        "Parquet canonical row identity is invalid"
                    )
                rows_seen += 1
    except LocalReleaseError:
        raise
    except Exception as exc:
        raise LocalReleaseError("Parquet row validation failed") from exc
    if rows_seen != descriptor.row_count:
        raise LocalReleaseError("Parquet scanned row count is inconsistent")


def _expected_original_runtime_shards() -> list[dict[str, Any]]:
    return [
        {
            "content_id": _raw_sha256_cid(bytes.fromhex(contract.sha256)),
            "release_path": contract.release_path,
            "row_count": contract.row_count,
            "sha256": contract.sha256,
            "size_bytes": contract.size_bytes,
            "source_path": contract.source_path,
        }
        for contract in PINNED_ORIGINAL_SHARDS
    ]


def _exact_integer(value: Any, expected: int) -> bool:
    return type(value) is int and value == expected


def _validate_original_data_manifest(
    manifest: Mapping[str, Any],
    artifacts: Sequence[ArtifactDescriptor],
    *,
    source_dataset_id: str,
    source_revision: str,
) -> bool:
    original_artifacts = tuple(
        item for item in artifacts if item.config_name == "original_data"
    )
    if tuple(item.path for item in original_artifacts) != tuple(
        contract.release_path for contract in PINNED_ORIGINAL_SHARDS
    ):
        raise LocalReleaseError(
            "complete original-data shard inventory is invalid"
        )
    row_indexes = tuple(
        item for item in artifacts if item.config_name == "original_row_index"
    )
    if (
        len(row_indexes) != 1
        or row_indexes[0].path != "indexes/original_rows.parquet"
        or row_indexes[0].row_count
        != sum(contract.row_count for contract in PINNED_ORIGINAL_SHARDS)
    ):
        raise LocalReleaseError("original-row index inventory is invalid")

    release_manifest = _object(
        manifest.get("release_manifest"), "canonical release manifest"
    )
    release_payload = _object(
        release_manifest.get("payload"), "release manifest payload"
    )
    if (
        release_manifest.get("profile") != ORIGINAL_MIRROR_PROFILE
        or release_payload.get("derived_security_ir_profile")
        != "public-metadata-and-body-digests"
    ):
        raise LocalReleaseError("original-data release profile is invalid")

    build_runtime = _object(
        manifest.get("build_runtime"), "manifest build_runtime"
    )
    original = _object(
        build_runtime.get("original_data"),
        "manifest original-data runtime",
    )
    if (
        original.get("byte_exact_upstream_copy") is not True
        or original.get("config_name") != "original_data"
        or original.get("mirror_profile") != ORIGINAL_MIRROR_PROFILE
        or original.get("operator_acknowledgement_required") is not True
        or original.get("row_index_config_name") != "original_row_index"
        or original.get("source_dataset_id") != PINNED_SOURCE_DATASET_ID
        or original.get("source_profile_sha256")
        != PINNED_SOURCE_PROFILE_SHA256
        or original.get("source_revision") != PINNED_SOURCE_REVISION
        or _canonical_json(original.get("shards"))
        != _canonical_json(_expected_original_runtime_shards())
        or source_dataset_id != PINNED_SOURCE_DATASET_ID
        or source_revision != PINNED_SOURCE_REVISION
    ):
        raise LocalReleaseError("original-data runtime binding is invalid")

    configs = _object(manifest.get("configs"), "manifest configs")
    if (
        configs.get("original_data") != "data/original/*.parquet"
        or configs.get("original_row_index")
        != "indexes/original_rows.parquet"
    ):
        raise LocalReleaseError("original-data config routing is invalid")
    counts = _object(manifest.get("counts"), "manifest counts")
    if (
        not _exact_integer(
            counts.get("original_data_bytes"),
            sum(contract.size_bytes for contract in PINNED_ORIGINAL_SHARDS),
        )
        or not _exact_integer(
            counts.get("original_data_rows"),
            sum(contract.row_count for contract in PINNED_ORIGINAL_SHARDS),
        )
        or not _exact_integer(
            counts.get("original_data_shards"),
            len(PINNED_ORIGINAL_SHARDS),
        )
        or not _exact_integer(
            counts.get("original_row_index_rows"),
            row_indexes[0].row_count,
        )
    ):
        raise LocalReleaseError("original-data manifest counts are invalid")
    parquet = _object(manifest.get("parquet"), "manifest parquet")
    compression = _object(
        parquet.get("compression"), "manifest parquet compression"
    )
    if (
        compression.get("derived_and_indexes") != "zstd"
        or compression.get("original_data") != "upstream_byte_exact"
        or not _exact_integer(
            parquet.get("physical_index_count"),
            len(COMPLETE_INDEX_PATHS),
        )
    ):
        raise LocalReleaseError("original-data compression binding is invalid")
    return True


def _validate_original_row_index(
    root: Path,
    descriptor: ArtifactDescriptor,
    shards: Sequence[ArtifactDescriptor],
    manifest: Mapping[str, Any],
    pq: Any,
) -> None:
    if tuple(item.path for item in shards) != tuple(
        contract.release_path for contract in PINNED_ORIGINAL_SHARDS
    ):
        raise LocalReleaseError("original-row index targets are invalid")
    expected_positions = [
        (contract, shard_offset)
        for contract in PINNED_ORIGINAL_SHARDS
        for shard_offset in range(contract.row_count)
    ]
    if descriptor.row_count != len(expected_positions):
        raise LocalReleaseError("original-row index row count is invalid")
    try:
        parquet = pq.ParquetFile(root / descriptor.path)
    except Exception as exc:
        raise LocalReleaseError("cannot open original-row index") from exc

    positions_seen = bytearray(len(expected_positions))
    source_cids: set[str] = set()
    statuses = {
        "adaptation_rejected": 0,
        "publication_rejected": 0,
        "admitted": 0,
    }
    previous_cid = ""
    rows_seen = 0
    try:
        batches = parquet.iter_batches(
            batch_size=1_024,
            columns=ORIGINAL_ROW_INDEX_COLUMNS,
        )
        for batch in batches:
            for row in batch.to_pylist():
                source_cid = row.get("security_ir_source_cid")
                source_row_index = row.get("source_row_index")
                source_status = row.get("source_status")
                if (
                    not isinstance(source_cid, str)
                    or not _CID_RE.fullmatch(source_cid)
                    or source_cid <= previous_cid
                    or source_cid in source_cids
                    or type(source_row_index) is not int
                    or not 0 <= source_row_index < len(expected_positions)
                    or positions_seen[source_row_index]
                    or source_status not in statuses
                ):
                    raise LocalReleaseError(
                        "original-row index identity coverage is invalid"
                    )
                contract, shard_offset = expected_positions[source_row_index]
                expected_domain = (
                    "cvefixes-security-ir/pinned-source-row"
                    if source_status == "admitted"
                    else "cvefixes-security-ir/rejected-source-row"
                )
                expected_identity_schema_version = (
                    "cvefixes-pinned-source-row/v1"
                    if source_status == "admitted"
                    else "cvefixes-rejected-source-row/v1"
                )
                if (
                    row.get("source_identity_domain") != expected_domain
                    or row.get("source_identity_schema_version")
                    != expected_identity_schema_version
                    or row.get("source_shard_cid")
                    != _raw_sha256_cid(bytes.fromhex(contract.sha256))
                    or row.get("source_shard_path") != contract.source_path
                    or row.get("source_shard_row_index") != shard_offset
                    or row.get("relative_path") != contract.release_path
                    or row.get("source_dataset_id")
                    != PINNED_SOURCE_DATASET_ID
                    or row.get("source_revision") != PINNED_SOURCE_REVISION
                    or row.get("schema_version")
                    != ORIGINAL_ROW_INDEX_SCHEMA_VERSION
                ):
                    raise LocalReleaseError(
                        "original-row index shard binding is invalid"
                    )
                positions_seen[source_row_index] = 1
                source_cids.add(source_cid)
                statuses[source_status] += 1
                previous_cid = source_cid
                rows_seen += 1
    except LocalReleaseError:
        raise
    except Exception as exc:
        raise LocalReleaseError("cannot scan original-row index") from exc
    if (
        rows_seen != len(expected_positions)
        or not all(positions_seen)
        or len(source_cids) != len(expected_positions)
    ):
        raise LocalReleaseError("original-row index coverage is incomplete")

    report = _json_bytes(
        _bounded_bytes(
            root / "evaluation-report.json",
            maximum=MAX_MANIFEST_BYTES,
            label="evaluation-report.json",
        ),
        "evaluation-report.json",
    )
    evaluation = _object(
        report.get("evaluation"), "evaluation report record"
    )
    evaluated_source_cids = evaluation.get("source_cids")
    if (
        not isinstance(evaluated_source_cids, list)
        or len(evaluated_source_cids) != len(source_cids)
        or set(evaluated_source_cids) != source_cids
    ):
        raise LocalReleaseError(
            "original-row index differs from evaluation provenance"
        )
    counts = _object(manifest.get("counts"), "manifest counts")
    if (
        not _exact_integer(
            counts.get("admitted_rows"),
            statuses["admitted"],
        )
        or not _exact_integer(
            counts.get("rejected_rows"),
            statuses["adaptation_rejected"]
            + statuses["publication_rejected"],
        )
    ):
        raise LocalReleaseError("original-row status counts are invalid")


def _validate_meta_index_bindings(
    root: Path,
    artifacts: Sequence[ArtifactDescriptor],
    *,
    complete_layout: bool,
    manifest: Mapping[str, Any] | None = None,
) -> None:
    try:
        import pyarrow.parquet as pq
    except ImportError as exc:  # pragma: no cover - release dependency in CI
        raise LocalReleaseError(
            "pyarrow is required to validate release indexes"
        ) from exc

    data = {
        item.path: item
        for item in artifacts
        if item.path.startswith("data/") and item.config_name
    }
    indexes = {
        item.path: item
        for item in artifacts
        if item.path.startswith("indexes/")
    }
    if not indexes:
        return

    if complete_layout:
        if set(indexes) != set(COMPLETE_INDEX_PATHS):
            raise LocalReleaseError(
                "complete layout must contain every physical index"
            )
        if manifest is None:
            raise LocalReleaseError("complete manifest binding is unavailable")
        grouped: dict[str, tuple[ArtifactDescriptor, ...]] = {
            config: tuple(
                sorted(
                    (
                        item
                        for item in data.values()
                        if item.config_name == config
                    ),
                    key=lambda item: item.path,
                )
            )
            for config in COMPLETE_DATA_CONFIG_PATHS
        }
        if any(not shards for shards in grouped.values()):
            raise LocalReleaseError(
                "complete layout must contain every indexed data family"
            )
        expected_families = {
            index_path: grouped[family]
            for index_path, family in _COMPLETE_INDEX_FAMILY.items()
        }
    else:
        unsupported = set(indexes) - {
            "indexes/corpus_chunks.parquet",
            "indexes/graph_node_chunks.parquet",
            "indexes/graph_edge_chunks.parquet",
        }
        if unsupported:
            raise LocalReleaseError(
                "legacy release contains complete-layout-only indexes"
            )
        expected_families = {}
        for path in indexes:
            stem = PurePosixPath(path).stem
            if stem == "graph_node_chunks":
                selected = (
                    item for item in data.values()
                    if item.config_name == "graph_node"
                )
            elif stem == "graph_edge_chunks":
                selected = (
                    item for item in data.values()
                    if item.config_name == "graph_edge"
                )
            else:
                selected = (
                    item for item in data.values()
                    if item.config_name not in {"graph_node", "graph_edge"}
                )
            expected_families[path] = tuple(
                sorted(selected, key=lambda item: item.path)
            )

    covered: set[str] = set()
    for index_path, shards in sorted(expected_families.items()):
        descriptor = indexes[index_path]
        family = (
            _COMPLETE_INDEX_FAMILY[index_path]
            if complete_layout
            else ""
        )
        if family == "original_data":
            if manifest is None:
                raise LocalReleaseError(
                    "complete manifest binding is unavailable"
                )
            _validate_original_row_index(
                root,
                descriptor,
                shards,
                manifest,
                pq,
            )
            covered.update(item.path for item in shards)
            continue
        try:
            rows = pq.read_table(root / descriptor.path).to_pylist()
        except Exception as exc:
            raise LocalReleaseError("cannot read release meta-index") from exc
        if len(rows) != len(shards):
            raise LocalReleaseError(
                "meta-index row inventory differs from its data family"
            )
        next_document_index = 0
        for shard_id, (row, target) in enumerate(
            zip(rows, shards, strict=True)
        ):
            if not isinstance(row, Mapping):
                raise LocalReleaseError("meta-index row must be an object")
            relative_path = row.get("relative_path")
            if relative_path != target.path or relative_path in covered:
                raise LocalReleaseError(
                    "meta-index pointers must cover unique data shards"
                )
            try:
                table = pq.read_table(root / target.path)
            except Exception as exc:
                raise LocalReleaseError(
                    "cannot read indexed release data shard"
                ) from exc
            table_rows = table.to_pylist()
            key_column = (
                _DATA_KEY_COLUMNS[family]
                if complete_layout
                else "record_id"
            )
            keys = [str(item[key_column]) for item in table_rows]
            if not keys or any(not key for key in keys):
                raise LocalReleaseError("indexed shard keys are invalid")
            expected_start: int
            expected_end: int
            if family in {"corpus", "bm25_documents"}:
                documents = [
                    int(item["document_index"]) for item in table_rows
                ]
                if documents != list(
                    range(
                        next_document_index,
                        next_document_index + len(documents),
                    )
                ):
                    raise LocalReleaseError(
                        "document-indexed shard is not dense and contiguous"
                    )
                expected_start = documents[0]
                expected_end = documents[-1]
                next_document_index = expected_end + 1
            elif family == "vectors":
                documents = [
                    int(item["document_index"]) for item in table_rows
                ]
                expected_start = min(documents)
                expected_end = max(documents)
            elif complete_layout:
                expected_start = -1
                expected_end = -1
            else:
                expected_start = next_document_index
                expected_end = expected_start + target.row_count - 1
                next_document_index = expected_end + 1
            expected_first = (
                keys[0] if complete_layout else min(keys)
            )
            expected_last = (
                keys[-1] if complete_layout else max(keys)
            )
            if (
                row.get("cid") != target.content_id
                or row.get("sha256") != target.sha256
                or row.get("size_bytes") != target.byte_length
                or row.get("row_count") != target.row_count
                or row.get("kind") != target.config_name
                or row.get("schema_version") != "cvefixes-hf-shard-meta/v1"
                or row.get("shard_id") != shard_id
                or row.get("start_document_index") != expected_start
                or row.get("end_document_index") != expected_end
                or row.get("first_key") != expected_first
                or row.get("last_key") != expected_last
            ):
                raise LocalReleaseError("meta-index shard binding is invalid")
            if complete_layout:
                _validate_complete_meta_stats(row, table_rows, family)
            covered.add(relative_path)
    if covered != set(data):
        raise LocalReleaseError(
            "meta-index pointers do not cover data shards exactly"
        )
    if complete_layout:
        _validate_complete_document_coverage(root, data.values(), pq)


def _validate_complete_meta_stats(
    row: Mapping[str, Any],
    table_rows: Sequence[Mapping[str, Any]],
    family: str,
) -> None:
    if family == "bm25_postings":
        terms = {str(item["term"]) for item in table_rows}
        posting_count = sum(
            len(item["document_indices"]) for item in table_rows
        )
        token_instances = sum(
            sum(int(value) for value in item["title_frequencies"])
            + sum(int(value) for value in item["body_frequencies"])
            for item in table_rows
        )
        if (
            row.get("posting_count") != posting_count
            or row.get("term_count") != len(terms)
            or row.get("token_instance_count") != token_instances
        ):
            raise LocalReleaseError("BM25 keyword meta statistics differ")
    elif family in {
        "graph_outgoing_adjacency",
        "graph_incoming_adjacency",
    }:
        direction = (
            "outgoing"
            if family == "graph_outgoing_adjacency"
            else "incoming"
        )
        pages = [int(item["page_index"]) for item in table_rows]
        if (
            row.get("adjacency_count")
            != sum(int(item["neighbor_count"]) for item in table_rows)
            or row.get("direction") != direction
            or row.get("first_page_index") != pages[0]
            or row.get("last_page_index") != pages[-1]
            or row.get("node_count")
            != len({str(item["node_cid"]) for item in table_rows})
        ):
            raise LocalReleaseError("graph adjacency meta statistics differ")
    elif family == "vectors":
        cluster_ids = {int(item["cluster_id"]) for item in table_rows}
        embeddings = table_rows[0]["embedding"]
        if (
            len(cluster_ids) != 1
            or row.get("cluster_id") != next(iter(cluster_ids))
            or not isinstance(row.get("chunk_in_cluster"), int)
            or not isinstance(row.get("centroid_shard_count"), int)
            or not 1 <= row["centroid_shard_count"] <= 2
            or not isinstance(row.get("dimension"), int)
            or row["dimension"] != len(embeddings)
            or not isinstance(row.get("model_name"), str)
            or not row["model_name"]
            or len(row.get("centroid") or ()) != row["dimension"]
            or len(row.get("shard_centroid") or ()) != row["dimension"]
        ):
            raise LocalReleaseError("vector routing meta statistics differ")


def _validate_complete_document_coverage(
    root: Path,
    artifacts: Sequence[ArtifactDescriptor],
    pq: Any,
) -> None:
    coverage: dict[str, dict[int, str]] = {}
    for config_name in ("corpus", "bm25_documents", "vectors"):
        observed: dict[int, str] = {}
        for descriptor in sorted(
            (
                item
                for item in artifacts
                if item.config_name == config_name
            ),
            key=lambda item: item.path,
        ):
            rows = pq.read_table(
                root / descriptor.path,
                columns=["document_index", "entry_cid"],
            ).to_pylist()
            for row in rows:
                document_index = int(row["document_index"])
                entry_cid = str(row["entry_cid"])
                if document_index in observed:
                    raise LocalReleaseError(
                        f"{config_name} repeats a document index"
                    )
                observed[document_index] = entry_cid
        coverage[config_name] = observed
    corpus = coverage["corpus"]
    if (
        sorted(corpus) != list(range(len(corpus)))
        or coverage["bm25_documents"] != corpus
        or coverage["vectors"] != corpus
    ):
        raise LocalReleaseError(
            "corpus, BM25, and vector document coverage differs"
        )


def _card_config_names(content: bytes) -> tuple[str, ...]:
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise LocalReleaseError("README.md must be valid UTF-8") from exc
    if not text.startswith("---\n") or "\n---\n" not in text[4:]:
        return ()
    front_matter = text[4:].split("\n---\n", 1)[0]
    names = tuple(
        match.group(1)
        for line in front_matter.splitlines()
        if (
            match := re.fullmatch(
                r"- config_name: ([a-z][a-z0-9_]{0,63})", line
            )
        )
    )
    if len(names) != len(set(names)):
        raise LocalReleaseError("dataset card repeats a config name")
    return names


def _parquet_feature_metadata(
    root: Path,
    artifacts: Sequence[ArtifactDescriptor],
    config_name: str,
) -> dict[str, dict[str, str]]:
    descriptors = tuple(
        item for item in artifacts if item.config_name == config_name
    )
    if not descriptors:
        raise LocalReleaseError("dataset config has no Parquet artifact")
    expected: dict[str, dict[str, str]] | None = None
    try:
        import pyarrow.parquet as pq

        for descriptor in descriptors:
            schema = pq.ParquetFile(root / descriptor.path).schema_arrow
            observed = {
                field.name: {"dtype": str(field.type)}
                for field in schema
            }
            if expected is None:
                expected = observed
            elif observed != expected:
                raise LocalReleaseError(
                    f"dataset config shard schemas differ: {config_name}"
                )
    except LocalReleaseError:
        raise
    except Exception as exc:
        raise LocalReleaseError(
            f"cannot inspect dataset config schema: {config_name}"
        ) from exc
    if expected is None:
        raise LocalReleaseError("dataset config has no Parquet schema")
    return expected


def _validate_manifest_index_inventory(
    value: Any,
    artifacts: Sequence[ArtifactDescriptor],
    *,
    complete_layout: bool,
) -> None:
    indexes = _object(value, "manifest indexes")
    indexed_artifacts = {
        PurePosixPath(item.path).stem: item
        for item in artifacts
        if item.path.startswith("indexes/")
    }
    if set(indexes) != set(indexed_artifacts):
        raise LocalReleaseError("manifest meta-index inventory is invalid")
    if complete_layout and set(indexes) != set(META_INDEX_CONFIGS):
        raise LocalReleaseError(
            "complete manifest must bind every physical index"
        )
    allowed = {
        "byte_length",
        "cid",
        "config_name",
        "content_id",
        "media_type",
        "path",
        "relative_path",
        "row_count",
        "sha256",
        "size_bytes",
    }
    for name, raw in indexes.items():
        item = _object(raw, f"manifest index {name}")
        if not set(item) <= allowed:
            raise LocalReleaseError(
                "manifest index descriptor has unexpected fields"
            )
        artifact = indexed_artifacts[name]
        path = item.get("path", item.get("relative_path"))
        cid = item.get("content_id", item.get("cid"))
        size = item.get("byte_length", item.get("size_bytes"))
        if (
            path != artifact.path
            or cid != artifact.content_id
            or item.get("sha256") != artifact.sha256
            or size != artifact.byte_length
            or (
                "row_count" in item
                and item["row_count"] != artifact.row_count
            )
            or (
                "config_name" in item
                and item["config_name"] != artifact.config_name
            )
            or (
                "media_type" in item
                and item["media_type"] != artifact.media_type
            )
        ):
            raise LocalReleaseError(
                f"manifest index descriptor differs: {name}"
            )


def load_local_release(
    release_directory: str | os.PathLike[str],
    *,
    expected_target: str | None = None,
) -> LocalRelease:
    """Fail-closed validation of a previously staged local release."""

    root = Path(release_directory)
    if not root.exists() or not root.is_dir() or root.is_symlink():
        raise LocalReleaseError("release directory must be a real directory")
    try:
        root = root.resolve(strict=True)
    except OSError as exc:
        raise LocalReleaseError("cannot resolve release directory") from exc

    manifest_path = root / "manifest.json"
    manifest_bytes = _bounded_bytes(
        manifest_path, maximum=MAX_MANIFEST_BYTES, label="manifest.json"
    )
    manifest = _json_bytes(manifest_bytes, "manifest.json")
    required_manifest_fields = {
        "artifacts",
        "dataset_id",
        "derived_dataset_root",
        "release_manifest",
        "release_root",
        "schema_version",
        "source",
    }
    manifest_fields = frozenset(manifest)
    if (
        not required_manifest_fields <= manifest_fields
        or not manifest_fields
        <= required_manifest_fields | _MANIFEST_OPTIONAL_FIELDS
    ):
        raise LocalReleaseError("manifest fields are not canonical")
    _safe_public_value(manifest)
    dataset_id = manifest.get("dataset_id")
    release_root = manifest.get("release_root")
    if (
        not isinstance(dataset_id, str)
        or not _DATASET_ID_RE.fullmatch(dataset_id)
        or (expected_target is not None and dataset_id != expected_target)
    ):
        raise LocalReleaseError("manifest target dataset does not match")
    if (
        not isinstance(release_root, str)
        or not _CID_RE.fullmatch(release_root)
        or manifest.get("schema_version") != RELEASE_SCHEMA_VERSION
    ):
        raise LocalReleaseError("manifest release identity is invalid")

    source = _object(manifest.get("source"), "manifest source")
    source_dataset_id = source.get("dataset_id")
    source_revision = source.get("source_revision")
    if (
        not isinstance(source_dataset_id, str)
        or not source_dataset_id
        or not isinstance(source_revision, str)
        or not source_revision
        or len(source_revision) > 256
    ):
        raise LocalReleaseError("manifest source binding is invalid")

    release_manifest = _object(
        manifest.get("release_manifest"), "canonical release manifest"
    )
    payload = _object(release_manifest.get("payload"), "release manifest payload")
    if (
        release_manifest.get("dataset_id") != dataset_id
        or payload.get("release_root") != release_root
        or payload.get("release_schema_version") != RELEASE_SCHEMA_VERSION
    ):
        raise LocalReleaseError("canonical release manifest binding is invalid")

    raw_artifacts = manifest.get("artifacts")
    if (
        not isinstance(raw_artifacts, list)
        or not raw_artifacts
        or len(raw_artifacts) > MAX_ARTIFACTS
    ):
        raise LocalReleaseError("manifest artifact inventory is invalid")
    artifacts = tuple(
        ArtifactDescriptor.from_dict(item) for item in raw_artifacts
    )
    paths = tuple(item.path for item in artifacts)
    if paths != tuple(sorted(paths)) or len(set(paths)) != len(paths):
        raise LocalReleaseError("artifact inventory must be sorted and unique")
    complete_data = tuple(
        item
        for item in artifacts
        if _complete_data_config(item.path) is not None
    )
    legacy_data = tuple(
        item
        for item in artifacts
        if item.path.startswith("data/")
        and _complete_data_config(item.path) is None
    )
    complete_layout = bool(complete_data)
    if complete_layout and legacy_data:
        raise LocalReleaseError(
            "complete and legacy data layouts cannot be mixed"
        )
    if complete_layout and LEGACY_RELEASE_METADATA_PATH in paths:
        raise LocalReleaseError(
            "complete release cannot contain reserved dataset_infos.json"
        )
    metadata_path = (
        COMPLETE_RELEASE_METADATA_PATH
        if complete_layout
        else LEGACY_RELEASE_METADATA_PATH
    )
    required = {"README.md", metadata_path, "evaluation-report.json"}
    if not required <= set(paths) or not any(item.config_name for item in artifacts):
        raise LocalReleaseError("release artifact inventory is incomplete")
    if complete_layout:
        observed_data_configs = {
            item.config_name for item in complete_data
        }
        if observed_data_configs != set(COMPLETE_DATA_CONFIG_PATHS):
            raise LocalReleaseError(
                "complete data-family inventory is incomplete"
            )
        observed_indexes = {
            item.path
            for item in artifacts
            if item.path.startswith("indexes/")
        }
        if observed_indexes != set(COMPLETE_INDEX_PATHS):
            raise LocalReleaseError(
                "complete physical index inventory is incomplete"
            )
    _validate_manifest_index_inventory(
        manifest.get("indexes", {}),
        artifacts,
        complete_layout=complete_layout,
    )
    for field in (
        "counts",
        "bm25",
        "vector",
        "graph",
        "parquet",
        "configs",
        "build_runtime",
    ):
        if field in manifest:
            _object(manifest[field], f"manifest {field}")
    if complete_layout and not {
        "counts",
        "bm25",
        "vector",
        "graph",
        "parquet",
        "configs",
        "build_runtime",
    } <= set(manifest):
        raise LocalReleaseError(
            "complete manifest metadata inventory is incomplete"
        )
    original_data_acknowledgement_required = False
    if complete_layout:
        original_data_acknowledgement_required = (
            _validate_original_data_manifest(
                manifest,
                artifacts,
                source_dataset_id=source_dataset_id,
                source_revision=source_revision,
            )
        )
    if (
        "primary_key" in manifest
        and manifest["primary_key"] != "entry_cid"
    ):
        raise LocalReleaseError(
            "release primary_key must be entry_cid"
        )

    actual_files: set[str] = set()
    for candidate in root.rglob("*"):
        if candidate.is_symlink():
            raise LocalReleaseError("release directory cannot contain symlinks")
        if candidate.is_file():
            actual_files.add(candidate.relative_to(root).as_posix())
        elif not candidate.is_dir():
            raise LocalReleaseError("release directory contains a special file")
    if actual_files != set(paths) | {"manifest.json"}:
        raise LocalReleaseError("local files do not exactly match the manifest")

    for descriptor in artifacts:
        path = root.joinpath(*PurePosixPath(descriptor.path).parts)
        content: bytes | None
        if _original_contract(descriptor.path) is not None:
            observed_size, digest = _stream_file_sha256(
                path,
                maximum=_artifact_byte_limit(descriptor.path),
                label=f"artifact {descriptor.path}",
            )
            content = None
        else:
            content = _bounded_bytes(
                path,
                maximum=_artifact_byte_limit(descriptor.path),
                label=f"artifact {descriptor.path}",
            )
            observed_size = len(content)
            digest = hashlib.sha256(content).digest()
        if (
            observed_size != descriptor.byte_length
            or digest.hex() != descriptor.sha256
        ):
            raise LocalReleaseError(
                f"artifact content mismatch: {descriptor.path}"
            )
        if (
            complete_layout
            and descriptor.path.endswith(".parquet")
            and descriptor.content_id
            != _raw_sha256_cid(digest)
        ):
            raise LocalReleaseError(
                f"artifact raw SHA-256 CID mismatch: {descriptor.path}"
            )
        if descriptor.config_name:
            _validate_parquet(
                path, descriptor, complete_layout=complete_layout
            )
        elif descriptor.path.endswith(".json"):
            if content is None:
                raise LocalReleaseError("JSON artifact content is unavailable")
            _safe_public_value(
                _json_bytes(content, descriptor.path),
                location=f"$.{descriptor.path}",
            )
        else:
            if content is None:
                raise LocalReleaseError("README.md content is unavailable")
            try:
                text = content.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise LocalReleaseError("README.md must be valid UTF-8") from exc
            if _SECRET_VALUE_RE.search(text):
                raise LocalReleaseError(
                    "secret-like value is forbidden in README.md"
                )
    _validate_meta_index_bindings(
        root,
        artifacts,
        complete_layout=complete_layout,
        manifest=manifest,
    )

    release_metadata = _json_bytes(
        _bounded_bytes(
            root / metadata_path,
            maximum=MAX_MANIFEST_BYTES,
            label=metadata_path,
        ),
        metadata_path,
    )
    configs = _object(release_metadata.get("configs"), "dataset configs")
    if (
        release_metadata.get("dataset_id") != dataset_id
        or release_metadata.get("derived_dataset_root")
        != manifest.get("derived_dataset_root")
        or release_metadata.get("schema_version") != PARQUET_SCHEMA_VERSION
        or not configs
    ):
        raise LocalReleaseError(f"{metadata_path} release binding is invalid")
    info_config_names = tuple(sorted(configs))
    if any(not _CONFIG_RE.fullmatch(name) for name in info_config_names):
        raise LocalReleaseError("dataset config name is invalid")
    all_shard_counts: dict[str, int] = {}
    for descriptor in artifacts:
        if descriptor.config_name:
            all_shard_counts[descriptor.config_name] = (
                all_shard_counts.get(descriptor.config_name, 0) + 1
            )
    if complete_layout:
        all_complete_configs = frozenset(all_shard_counts)
        if (
            frozenset(info_config_names)
            not in {COMPLETE_VIEWER_CONFIGS, all_complete_configs}
            or not COMPLETE_VIEWER_CONFIGS <= all_complete_configs
            or all_complete_configs
            != COMPLETE_VIEWER_CONFIGS | _HIDDEN_INDEX_CONFIGS
        ):
            raise LocalReleaseError(
                "complete dataset config inventory is invalid"
            )
        config_names = tuple(sorted(COMPLETE_VIEWER_CONFIGS))
        card_configs = _card_config_names(
            _bounded_bytes(
                root / "README.md",
                maximum=MAX_MANIFEST_BYTES,
                label="README.md",
            )
        )
        if set(card_configs) != COMPLETE_VIEWER_CONFIGS:
            raise LocalReleaseError(
                "dataset card must expose the complete Viewer config inventory"
            )
    else:
        config_names = info_config_names
        if tuple(sorted(all_shard_counts)) != config_names:
            raise LocalReleaseError(
                "dataset configs do not match Parquet shards"
            )
    for name in info_config_names:
        config = _object(configs[name], f"dataset config {name}")
        features = _object(config.get("features"), f"dataset config {name} features")
        splits = _object(config.get("splits"), f"dataset config {name} splits")
        train = _object(splits.get("train"), f"dataset config {name} train split")
        expected_columns = _CONFIG_COLUMNS.get(name)
        if expected_columns is None:
            expected_columns = (
                META_INDEX_COLUMNS
                if any(
                    item.path.startswith("indexes/")
                    for item in artifacts
                    if item.config_name == name
                )
                else EXPECTED_COLUMNS
            )
        if set(features) != set(expected_columns):
            raise LocalReleaseError("dataset config feature schema is invalid")
        if (
            complete_layout
            and dict(features)
            != _parquet_feature_metadata(root, artifacts, name)
        ):
            raise LocalReleaseError(
                "dataset config feature types differ from Parquet"
            )
        expected_rows = sum(
            item.row_count for item in artifacts if item.config_name == name
        )
        expected_bytes = sum(
            item.byte_length for item in artifacts if item.config_name == name
        )
        if (
            train.get("num_examples") != expected_rows
            or train.get("num_bytes") != expected_bytes
        ):
            raise LocalReleaseError("dataset config row inventory is invalid")
    shard_counts = {
        name: all_shard_counts[name] for name in config_names
    }

    declared_shards = release_manifest.get("shard_cids")
    if (
        not isinstance(declared_shards, list)
        or set(declared_shards)
        != {
            item.content_id
            for item in artifacts
            if item.config_name and item.path.startswith("data/")
        }
    ):
        raise LocalReleaseError("release manifest shard inventory is invalid")

    return LocalRelease(
        directory=root,
        dataset_id=dataset_id,
        source_dataset_id=source_dataset_id,
        source_revision=source_revision,
        release_root=release_root,
        manifest_bytes=manifest_bytes,
        manifest_sha256=hashlib.sha256(manifest_bytes).hexdigest(),
        artifacts=artifacts,
        config_names=config_names,
        config_shard_counts=tuple(sorted(shard_counts.items())),
        complete_layout=complete_layout,
        original_data_acknowledgement_required=(
            original_data_acknowledgement_required
        ),
    )


class HubGateway(Protocol):
    """Small injectable side-effect boundary used by the command and tests."""

    def authenticate(self, token: str) -> str: ...

    def head(self, repo_id: str, token: str | None) -> str: ...

    def revisions(
        self, repo_id: str, token: str | None, *, limit: int
    ) -> Sequence[str]: ...

    def read_file(
        self, repo_id: str, revision: str, path: str, token: str | None
    ) -> bytes: ...

    def upload(
        self,
        release: LocalRelease,
        token: str,
        *,
        parent_commit: str,
        commit_message: str,
        commit_description: str,
    ) -> str: ...

    def viewer(
        self,
        endpoint: str,
        params: Mapping[str, str],
        token: str | None,
    ) -> Mapping[str, Any]: ...


class HuggingFaceHubGateway:
    """Production Hub gateway with bounded, cache-free remote reads."""

    def __init__(
        self,
        *,
        hub_base_url: str = "https://huggingface.co",
        viewer_base_url: str = "https://datasets-server.huggingface.co",
        timeout_seconds: float = 30.0,
    ) -> None:
        self._hub_base_url = hub_base_url.rstrip("/")
        self._viewer_base_url = viewer_base_url.rstrip("/")
        self._timeout = timeout_seconds

    @staticmethod
    def _api() -> Any:
        try:
            from huggingface_hub import HfApi
        except ImportError as exc:  # pragma: no cover - normal project dependency
            raise PublicationError("huggingface_hub is required for publication") from exc
        return HfApi()

    def authenticate(self, token: str) -> str:
        try:
            identity = self._api().whoami(token=token)
        except Exception as exc:
            raise AuthenticationError("Hugging Face authentication failed") from exc
        if not isinstance(identity, Mapping):
            raise AuthenticationError("Hugging Face returned no authenticated identity")
        principal = identity.get("name") or identity.get("fullname")
        if not isinstance(principal, str) or not principal.strip():
            raise AuthenticationError("Hugging Face returned no authenticated identity")
        return principal.strip()

    def head(self, repo_id: str, token: str | None) -> str:
        try:
            info = self._api().repo_info(
                repo_id=repo_id,
                repo_type="dataset",
                revision="main",
                token=token,
            )
            commit = getattr(info, "sha", "")
        except Exception as exc:
            raise RemoteVerificationError("cannot resolve Hub dataset head") from exc
        if not isinstance(commit, str) or not _COMMIT_RE.fullmatch(commit):
            raise RemoteVerificationError("Hub dataset head is not immutable")
        return commit

    def revisions(
        self, repo_id: str, token: str | None, *, limit: int
    ) -> Sequence[str]:
        try:
            commits = self._api().list_repo_commits(
                repo_id, repo_type="dataset", token=token
            )
        except Exception as exc:
            raise RemoteVerificationError("cannot inspect Hub dataset history") from exc
        result: list[str] = []
        for item in commits[:limit]:
            commit = getattr(item, "commit_id", "")
            if isinstance(commit, str) and _COMMIT_RE.fullmatch(commit):
                result.append(commit)
        return tuple(result)

    def _read_url(
        self, url: str, token: str | None, *, maximum: int
    ) -> bytes:
        headers = {"Accept": "application/json", "User-Agent": "cvefixes-security-ir-publisher/1"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        request = Request(url, headers=headers)
        try:
            with urlopen(request, timeout=self._timeout) as response:
                length = response.headers.get("Content-Length")
                if length and int(length) > maximum:
                    raise RemoteVerificationError("remote response exceeds byte limit")
                content = response.read(maximum + 1)
        except RemoteVerificationError:
            raise
        except (HTTPError, URLError, OSError, ValueError) as exc:
            raise RemoteVerificationError("bounded remote read failed") from exc
        if len(content) > maximum:
            raise RemoteVerificationError("remote response exceeds byte limit")
        return content

    def read_file(
        self, repo_id: str, revision: str, path: str, token: str | None
    ) -> bytes:
        if not _DATASET_ID_RE.fullmatch(repo_id) or not _COMMIT_RE.fullmatch(revision):
            raise RemoteVerificationError("unsafe Hub file binding")
        safe_path = _safe_artifact_path(path) if path != "manifest.json" else path
        url = (
            f"{self._hub_base_url}/datasets/{quote(repo_id, safe='/')}/resolve/"
            f"{quote(revision, safe='')}/{quote(safe_path, safe='/')}"
        )
        maximum = (
            MAX_MANIFEST_BYTES
            if path.endswith((".json", ".md"))
            else _artifact_byte_limit(path)
        )
        return self._read_url(url, token, maximum=maximum)

    def upload(
        self,
        release: LocalRelease,
        token: str,
        *,
        parent_commit: str,
        commit_message: str,
        commit_description: str,
    ) -> str:
        patterns = [item.path for item in release.artifacts] + ["manifest.json"]
        try:
            result = self._api().upload_folder(
                repo_id=release.dataset_id,
                repo_type="dataset",
                folder_path=release.directory,
                token=token,
                revision="main",
                parent_commit=parent_commit,
                commit_message=commit_message,
                commit_description=commit_description,
                allow_patterns=patterns,
                delete_patterns=[
                    "README.md",
                    COMPLETE_RELEASE_METADATA_PATH,
                    LEGACY_RELEASE_METADATA_PATH,
                    "evaluation-report.json",
                    "manifest.json",
                    "data/**",
                    "indexes/**",
                ],
            )
            commit = getattr(result, "oid", "") or getattr(result, "commit_id", "")
        except Exception as exc:
            raise PublicationError("Hugging Face upload failed") from exc
        if not isinstance(commit, str) or not _COMMIT_RE.fullmatch(commit):
            raise PublicationError("upload did not return an immutable Hub commit")
        return commit

    def viewer(
        self,
        endpoint: str,
        params: Mapping[str, str],
        token: str | None,
    ) -> Mapping[str, Any]:
        if endpoint not in {"is-valid", "splits", "parquet", "first-rows"}:
            raise RemoteVerificationError("unsupported Dataset Viewer endpoint")
        url = f"{self._viewer_base_url}/{endpoint}?{urlencode(params)}"
        content = self._read_url(
            url, token, maximum=MAX_VIEWER_RESPONSE_BYTES
        )
        try:
            value = json.loads(content)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ViewerNotReadyError("Dataset Viewer returned invalid JSON") from exc
        if not isinstance(value, Mapping):
            raise ViewerNotReadyError("Dataset Viewer returned an invalid object")
        return value


def _remote_tuple(content: bytes) -> tuple[str, str, str] | None:
    try:
        value = json.loads(content)
        source = value["source"]
        result = (
            value["dataset_id"],
            source["source_revision"],
            value["release_root"],
        )
    except (KeyError, TypeError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not all(isinstance(item, str) for item in result):
        return None
    return result


def find_existing_revision(
    gateway: HubGateway,
    release: LocalRelease,
    token: str | None,
    *,
    head: str,
) -> str | None:
    """Find a prior identical tuple without making a second release commit."""

    revisions = [head]
    revisions.extend(
        revision
        for revision in gateway.revisions(
            release.dataset_id, token, limit=MAX_HISTORY_COMMITS
        )
        if revision != head
    )
    expected = (
        release.dataset_id,
        release.source_revision,
        release.release_root,
    )
    for revision in revisions[:MAX_HISTORY_COMMITS]:
        if not isinstance(revision, str) or not _COMMIT_RE.fullmatch(revision):
            raise RemoteVerificationError(
                "Hub history returned a non-immutable revision"
            )
        try:
            remote = gateway.read_file(
                release.dataset_id, revision, "manifest.json", token
            )
        except RemoteVerificationError:
            continue
        if _remote_tuple(remote) == expected:
            if remote != release.manifest_bytes:
                raise RemoteVerificationError(
                    "existing release tuple has non-identical manifest bytes"
                )
            return revision
    return None


def _feature_names(response: Mapping[str, Any]) -> tuple[str, ...]:
    features = response.get("features")
    if not isinstance(features, list):
        raise ViewerNotReadyError("Dataset Viewer features are unavailable")
    names: list[str] = []
    for feature in features:
        if not isinstance(feature, Mapping) or not isinstance(feature.get("name"), str):
            raise ViewerNotReadyError("Dataset Viewer feature schema is malformed")
        names.append(feature["name"])
    return tuple(names)


def verify_dataset_viewer(
    gateway: HubGateway,
    release: LocalRelease,
    token: str | None,
) -> dict[str, Any]:
    """Verify Viewer validity, configs/splits, shard counts, and row schema."""

    validity = gateway.viewer(
        "is-valid", {"dataset": release.dataset_id}, token
    )
    if validity.get("viewer") is not True:
        raise ViewerNotReadyError("Dataset Viewer does not mark the dataset valid")

    splits_response = gateway.viewer(
        "splits", {"dataset": release.dataset_id}, token
    )
    raw_splits = splits_response.get("splits")
    if not isinstance(raw_splits, list):
        raise ViewerNotReadyError("Dataset Viewer splits are unavailable")
    actual_splits = {
        (item.get("config"), item.get("split"))
        for item in raw_splits
        if isinstance(item, Mapping)
    }
    expected_splits = {(name, "train") for name in release.config_names}
    if actual_splits != expected_splits:
        raise ViewerNotReadyError("Dataset Viewer split inventory mismatch")

    parquet_response = gateway.viewer(
        "parquet", {"dataset": release.dataset_id}, token
    )
    raw_parquet = parquet_response.get("parquet_files")
    if not isinstance(raw_parquet, list):
        raise ViewerNotReadyError("Dataset Viewer Parquet inventory is unavailable")
    viewer_shards: dict[str, list[dict[str, Any]]] = {
        name: [] for name in release.config_names
    }
    for item in raw_parquet:
        if not isinstance(item, Mapping):
            raise ViewerNotReadyError("Dataset Viewer Parquet item is malformed")
        config = item.get("config")
        if (
            config not in viewer_shards
            or item.get("split") != "train"
            or not isinstance(item.get("filename"), str)
            or type(item.get("size")) is not int
            or item["size"] <= 0
        ):
            raise ViewerNotReadyError("Dataset Viewer Parquet binding is invalid")
        viewer_shards[config].append(
            {"filename": item["filename"], "size": item["size"]}
        )
    for config, expected_count in release.config_shard_counts:
        if len(viewer_shards[config]) != expected_count:
            raise ViewerNotReadyError("Dataset Viewer shard count mismatch")

    for config in release.config_names:
        expected_columns = release.columns_for_config(config)
        first_rows = gateway.viewer(
            "first-rows",
            {
                "config": config,
                "dataset": release.dataset_id,
                "split": "train",
            },
            token,
        )
        if (
            first_rows.get("dataset") not in {None, release.dataset_id}
            or first_rows.get("config") not in {None, config}
            or first_rows.get("split") not in {None, "train"}
            or _feature_names(first_rows) != expected_columns
        ):
            raise ViewerNotReadyError("Dataset Viewer feature binding mismatch")
        rows = first_rows.get("rows")
        if not isinstance(rows, list) or not rows:
            raise ViewerNotReadyError("Dataset Viewer returned no verification row")
        first = rows[0]
        row = first.get("row") if isinstance(first, Mapping) else None
        if not isinstance(row, Mapping) or tuple(row) != expected_columns:
            raise ViewerNotReadyError("Dataset Viewer row schema mismatch")
        if config == "original_data":
            if (
                not isinstance(row.get("cve_id"), str)
                or not _CVE_ID_RE.fullmatch(row["cve_id"])
                or not isinstance(row.get("hash"), str)
                or not _GIT_HASH_RE.fullmatch(row["hash"])
            ):
                raise ViewerNotReadyError(
                    "Dataset Viewer original-data identity mismatch"
                )
            continue
        if config == "original_row_index":
            if (
                not isinstance(row.get("security_ir_source_cid"), str)
                or not _CID_RE.fullmatch(row["security_ir_source_cid"])
                or row.get("schema_version")
                != ORIGINAL_ROW_INDEX_SCHEMA_VERSION
            ):
                raise ViewerNotReadyError(
                    "Dataset Viewer original-row index binding mismatch"
                )
            continue
        if expected_columns[: len(META_INDEX_COLUMNS)] == META_INDEX_COLUMNS:
            if (
                row.get("schema_version") != "cvefixes-hf-shard-meta/v1"
                or not isinstance(row.get("relative_path"), str)
                or not row["relative_path"].startswith("data/")
                or not isinstance(row.get("cid"), str)
                or not _CID_RE.fullmatch(row["cid"])
            ):
                raise ViewerNotReadyError(
                    "Dataset Viewer meta-index row binding mismatch"
                )
            continue
        if config in COMPLETE_DATA_CONFIG_PATHS:
            key_column = _DATA_KEY_COLUMNS[config]
            key = row.get(key_column)
            if (
                not isinstance(key, str)
                or not key
                or not isinstance(row.get("schema_version"), str)
                or not row["schema_version"]
            ):
                raise ViewerNotReadyError(
                    "Dataset Viewer indexed data row is malformed"
                )
            continue
        if row.get("record_type") != config:
            raise ViewerNotReadyError("Dataset Viewer row crossed configurations")
        try:
            canonical_record = json.loads(row["record_json"])
        except (KeyError, TypeError, json.JSONDecodeError) as exc:
            raise ViewerNotReadyError(
                "Dataset Viewer row lacks canonical record JSON"
            ) from exc
        if (
            not isinstance(canonical_record, Mapping)
            or canonical_record.get("record_id") != row.get("record_id")
            or canonical_record.get("record_type") != config
        ):
            raise ViewerNotReadyError("Dataset Viewer row identity mismatch")

    return {
        "columns": {
            name: list(release.columns_for_config(name))
            for name in release.config_names
        },
        "index_columns": list(META_INDEX_COLUMNS),
        "configs": list(release.config_names),
        "shards": {
            key: sorted(value, key=lambda item: item["filename"])
            for key, value in sorted(viewer_shards.items())
        },
        "splits": [
            {"config": config, "split": split}
            for config, split in sorted(actual_splits)
        ],
        "verified": True,
    }


def verify_remote_release(
    gateway: HubGateway,
    release: LocalRelease,
    revision: str,
    token: str | None,
    *,
    viewer_attempts: int = 1,
    viewer_delay_seconds: float = 0.0,
) -> dict[str, Any]:
    """Verify a stable immutable revision and its corresponding Viewer output."""

    if (
        type(viewer_attempts) is not int
        or not 1 <= viewer_attempts <= 60
        or viewer_delay_seconds < 0
        or viewer_delay_seconds > 60
    ):
        raise PublicationError("Dataset Viewer retry bounds are invalid")
    if gateway.head(release.dataset_id, token) != revision:
        raise RemoteVerificationError(
            "target head does not match the release revision"
        )
    remote_manifest = gateway.read_file(
        release.dataset_id, revision, "manifest.json", token
    )
    if (
        remote_manifest != release.manifest_bytes
        or hashlib.sha256(remote_manifest).hexdigest() != release.manifest_sha256
    ):
        raise RemoteVerificationError("remote manifest verification failed")

    remote_artifacts: list[dict[str, Any]] = []
    for artifact in release.artifacts:
        content = gateway.read_file(
            release.dataset_id, revision, artifact.path, token
        )
        if (
            len(content) != artifact.byte_length
            or hashlib.sha256(content).hexdigest() != artifact.sha256
        ):
            raise RemoteVerificationError(
                f"remote artifact verification failed: {artifact.path}"
            )
        remote_artifacts.append(artifact.receipt_dict())

    viewer_result: dict[str, Any] | None = None
    last_error: ViewerNotReadyError | None = None
    for attempt in range(viewer_attempts):
        try:
            viewer_result = verify_dataset_viewer(gateway, release, token)
            break
        except ViewerNotReadyError as exc:
            last_error = exc
            if attempt + 1 < viewer_attempts and viewer_delay_seconds:
                time.sleep(viewer_delay_seconds)
    if viewer_result is None:
        raise last_error or ViewerNotReadyError(
            "Dataset Viewer verification did not complete"
        )
    if gateway.head(release.dataset_id, token) != revision:
        raise RemoteVerificationError(
            "target head changed during remote verification"
        )
    return {
        "artifacts": remote_artifacts,
        "dataset_viewer": viewer_result,
        "manifest_sha256": release.manifest_sha256,
        "remote_artifacts_verified": True,
        "remote_manifest_verified": True,
        "remote_revision_verified": True,
    }


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _receipt(
    release: LocalRelease,
    *,
    principal: str,
    revision: str,
    operation: str,
    verification: Mapping[str, Any],
    proposed_at: str,
) -> dict[str, Any]:
    receipt = {
        "authoritative": False,
        "grants_completion_authority": False,
        "grants_execution_authority": False,
        "hub_commit": revision,
        "idempotency": {
            "key": release.idempotency_key,
            "release_root": release.release_root,
            "source_revision": release.source_revision,
            "target_repo": release.dataset_id,
        },
        "operation": operation,
        "principal": principal,
        "proposed_at": proposed_at,
        "schema_version": PUBLICATION_RECEIPT_VERSION,
        "source_dataset_id": release.source_dataset_id,
        "status": "proposed",
        "verification": dict(verification),
    }
    _safe_public_value(receipt)
    return receipt


def publish_release(
    release_directory: str | os.PathLike[str],
    *,
    target_repo: str = DEFAULT_TARGET_REPO,
    execute: bool = False,
    acknowledge_original_data_mirror: bool = False,
    token_env: str = "HF_TOKEN",
    gateway: HubGateway | None = None,
    viewer_attempts: int = 1,
    viewer_delay_seconds: float = 0.0,
    now: Any = _utc_now,
) -> dict[str, Any]:
    """Plan or execute one idempotent publication attempt."""

    if type(execute) is not bool:
        raise PublicationError("execute must be boolean")
    if type(acknowledge_original_data_mirror) is not bool:
        raise PublicationError(
            "original-data mirror acknowledgement must be boolean"
        )
    if acknowledge_original_data_mirror and not execute:
        raise PublicationError(
            "original-data mirror acknowledgement requires execute"
        )
    if not _DATASET_ID_RE.fullmatch(target_repo):
        raise PublicationError("target repo must be owner/name")
    if not _ENV_RE.fullmatch(token_env):
        raise PublicationError("token environment variable name is invalid")
    release = load_local_release(
        release_directory, expected_target=target_repo
    )
    plan = {
        "artifact_count": len(release.artifacts) + 1,
        "dry_run": True,
        "idempotency_key": release.idempotency_key,
        "release_root": release.release_root,
        "schema_version": PUBLICATION_RECEIPT_VERSION,
        "shard_count": len(release.parquet_artifacts),
        "source_dataset_id": release.source_dataset_id,
        "source_revision": release.source_revision,
        "status": "planned",
        "target_repo": release.dataset_id,
        "original_data_mirror_acknowledgement_required": (
            release.original_data_acknowledgement_required
        ),
    }
    if not execute:
        return plan
    if (
        release.original_data_acknowledgement_required
        and not acknowledge_original_data_mirror
    ):
        raise PublicationError(
            "execute requires --acknowledge-original-data-mirror"
        )

    token = os.environ.get(token_env)
    if not isinstance(token, str) or not token:
        raise AuthenticationError(
            f"execute requires a token in environment variable {token_env}"
        )
    client = gateway or HuggingFaceHubGateway()
    principal = client.authenticate(token)
    head = client.head(release.dataset_id, token)
    existing = find_existing_revision(
        client, release, token, head=head
    )
    if existing is not None:
        revision = existing
        operation = "verified_existing"
        if existing != head:
            raise RemoteVerificationError(
                "matching historical release is not the target head"
            )
    else:
        revision = client.upload(
            release,
            token,
            parent_commit=head,
            commit_message=(
                f"Publish CVEfixes Security IR {release.release_root}"
            ),
            commit_description=(
                f"Idempotency-Key: {release.idempotency_key}\n"
                f"Source-Revision: {release.source_revision}"
            ),
        )
        operation = "uploaded"
    verification = verify_remote_release(
        client,
        release,
        revision,
        token,
        viewer_attempts=viewer_attempts,
        viewer_delay_seconds=viewer_delay_seconds,
    )
    return _receipt(
        release,
        principal=principal,
        revision=revision,
        operation=operation,
        verification=verification,
        proposed_at=now(),
    )


def _receipt_release(receipt: Mapping[str, Any]) -> LocalRelease:
    """Build the bounded verification projection carried by a receipt."""

    if set(receipt) != {
        "authoritative",
        "grants_completion_authority",
        "grants_execution_authority",
        "hub_commit",
        "idempotency",
        "operation",
        "principal",
        "proposed_at",
        "schema_version",
        "source_dataset_id",
        "status",
        "verification",
    }:
        raise LocalReleaseError("publication receipt fields are not canonical")
    if (
        receipt.get("schema_version") != PUBLICATION_RECEIPT_VERSION
        or receipt.get("status") != "proposed"
        or receipt.get("authoritative") is not False
        or receipt.get("grants_completion_authority") is not False
        or receipt.get("grants_execution_authority") is not False
        or receipt.get("operation") not in {"uploaded", "verified_existing"}
    ):
        raise LocalReleaseError("publication receipt authority is invalid")
    if (
        not isinstance(receipt.get("principal"), str)
        or not receipt["principal"].strip()
        or not isinstance(receipt.get("proposed_at"), str)
        or not receipt["proposed_at"].endswith("Z")
    ):
        raise LocalReleaseError("publication receipt provenance is invalid")
    _safe_public_value(receipt)
    binding = _object(receipt.get("idempotency"), "receipt idempotency")
    verification = _object(receipt.get("verification"), "receipt verification")
    raw_artifacts = verification.get("artifacts")
    if not isinstance(raw_artifacts, list) or not raw_artifacts:
        raise LocalReleaseError("receipt artifact inventory is invalid")
    artifacts: list[ArtifactDescriptor] = []
    for raw in raw_artifacts:
        item = _object(raw, "receipt artifact")
        expected = {
            "byte_length",
            "config_name",
            "content_id",
            "path",
            "row_count",
            "sha256",
        }
        if set(item) != expected:
            raise LocalReleaseError("receipt artifact fields are invalid")
        descriptor_value = {
            "byte_length": item["byte_length"],
            "content_id": item["content_id"],
            "media_type": (
                "application/vnd.apache.parquet"
                if item["config_name"]
                else (
                    "text/markdown; charset=utf-8"
                    if item["path"] == "README.md"
                    else "application/json"
                )
            ),
            "path": item["path"],
            "sha256": item["sha256"],
        }
        if item["config_name"]:
            descriptor_value["config_name"] = item["config_name"]
            descriptor_value["row_count"] = item["row_count"]
        elif item["row_count"] != 0:
            raise LocalReleaseError("receipt non-shard row count is invalid")
        artifacts.append(ArtifactDescriptor.from_dict(descriptor_value))
    if (
        tuple(item.path for item in artifacts)
        != tuple(sorted(item.path for item in artifacts))
        or len({item.path for item in artifacts}) != len(artifacts)
    ):
        raise LocalReleaseError("receipt artifact inventory is not canonical")
    viewer = _object(verification.get("dataset_viewer"), "receipt Dataset Viewer")
    configs = viewer.get("configs")
    if (
        verification.get("remote_artifacts_verified") is not True
        or verification.get("remote_manifest_verified") is not True
        or verification.get("remote_revision_verified") is not True
        or viewer.get("verified") is not True
        or not isinstance(configs, list)
        or not configs
        or configs != sorted(set(configs))
        or any(
            not isinstance(config, str) or not _CONFIG_RE.fullmatch(config)
            for config in configs
        )
    ):
        raise LocalReleaseError("receipt Dataset Viewer proof is invalid")
    receipt_columns = viewer.get("columns")
    if isinstance(receipt_columns, list):
        if receipt_columns != list(EXPECTED_COLUMNS):
            raise LocalReleaseError(
                "receipt Dataset Viewer columns are invalid"
            )
    elif isinstance(receipt_columns, Mapping):
        if set(receipt_columns) != set(configs):
            raise LocalReleaseError(
                "receipt Dataset Viewer columns are incomplete"
            )
        for config in configs:
            paths = {
                item.path
                for item in artifacts
                if item.config_name == config
            }
            if not paths:
                raise LocalReleaseError(
                    "receipt Viewer config has no artifact"
                )
            expected_columns = _CONFIG_COLUMNS.get(config)
            if expected_columns is None:
                expected_columns = (
                    META_INDEX_COLUMNS
                    if all(path.startswith("indexes/") for path in paths)
                    else EXPECTED_COLUMNS
                )
            if receipt_columns.get(config) != list(expected_columns):
                raise LocalReleaseError(
                    "receipt Dataset Viewer columns differ"
                )
    else:
        raise LocalReleaseError(
            "receipt Dataset Viewer columns are invalid"
        )
    shard_counts = tuple(
        sorted(
            (
                config,
                sum(1 for item in artifacts if item.config_name == config),
            )
            for config in configs
        )
    )
    dataset_id = binding.get("target_repo")
    source_revision = binding.get("source_revision")
    release_root = binding.get("release_root")
    source_dataset_id = receipt.get("source_dataset_id")
    manifest_sha = verification.get("manifest_sha256")
    if (
        not isinstance(dataset_id, str)
        or not _DATASET_ID_RE.fullmatch(dataset_id)
        or not isinstance(source_revision, str)
        or not source_revision
        or not isinstance(source_dataset_id, str)
        or not source_dataset_id
        or not isinstance(release_root, str)
        or not _CID_RE.fullmatch(release_root)
        or not isinstance(manifest_sha, str)
        or not _SHA256_RE.fullmatch(manifest_sha)
    ):
        raise LocalReleaseError("receipt release binding is invalid")
    expected_key = "cvefixes-publication:" + hashlib.sha256(
        _canonical_json(
            {
                "release_root": release_root,
                "source_revision": source_revision,
                "target_repo": dataset_id,
            }
        )
    ).hexdigest()
    if binding.get("key") != expected_key:
        raise LocalReleaseError("receipt idempotency key is invalid")
    return LocalRelease(
        directory=Path(),
        dataset_id=dataset_id,
        source_dataset_id=source_dataset_id,
        source_revision=source_revision,
        release_root=release_root,
        manifest_bytes=b"",
        manifest_sha256=manifest_sha,
        artifacts=tuple(artifacts),
        config_names=tuple(configs),
        config_shard_counts=shard_counts,
        complete_layout=any(
            _complete_data_config(item.path) is not None
            for item in artifacts
        ),
    )


def verify_receipt(
    receipt_path: str | os.PathLike[str],
    *,
    gateway: HubGateway | None = None,
    token_env: str = "HF_TOKEN",
) -> dict[str, Any]:
    """Read-only verification of a proposed publication receipt."""

    if not _ENV_RE.fullmatch(token_env):
        raise PublicationError("token environment variable name is invalid")
    content = _bounded_bytes(
        Path(receipt_path),
        maximum=MAX_MANIFEST_BYTES,
        label="publication receipt",
    )
    receipt = _json_bytes(content, "publication receipt")
    release = _receipt_release(receipt)
    revision = receipt.get("hub_commit")
    if not isinstance(revision, str) or not _COMMIT_RE.fullmatch(revision):
        raise LocalReleaseError("receipt Hub commit is invalid")
    token = os.environ.get(token_env) or None
    client = gateway or HuggingFaceHubGateway()
    if client.head(release.dataset_id, token) != revision:
        raise RemoteVerificationError("receipt commit is not the target head")
    manifest = client.read_file(
        release.dataset_id, revision, "manifest.json", token
    )
    if hashlib.sha256(manifest).hexdigest() != release.manifest_sha256:
        raise RemoteVerificationError("receipt remote manifest digest mismatch")
    if _remote_tuple(manifest) != (
        release.dataset_id,
        release.source_revision,
        release.release_root,
    ):
        raise RemoteVerificationError("receipt remote manifest binding mismatch")
    for artifact in release.artifacts:
        remote = client.read_file(
            release.dataset_id, revision, artifact.path, token
        )
        if (
            len(remote) != artifact.byte_length
            or hashlib.sha256(remote).hexdigest() != artifact.sha256
        ):
            raise RemoteVerificationError(
                f"receipt remote artifact mismatch: {artifact.path}"
            )
    viewer = verify_dataset_viewer(client, release, token)
    return {
        "hub_commit": revision,
        "release_root": release.release_root,
        "schema_version": PUBLICATION_RECEIPT_VERSION,
        "status": "verified",
        "target_repo": release.dataset_id,
        "verification": {
            "dataset_viewer": viewer,
            "remote_artifacts_verified": True,
            "remote_manifest_verified": True,
            "remote_revision_verified": True,
        },
    }


def write_receipt(
    receipt: Mapping[str, Any], destination: str | os.PathLike[str]
) -> None:
    """Atomically create a receipt without overwriting operator evidence."""

    path = Path(destination)
    if path.exists() or path.is_symlink():
        raise PublicationError("receipt destination already exists")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    if temporary.exists() or temporary.is_symlink():
        raise PublicationError("receipt temporary destination already exists")
    content = _canonical_json(receipt) + b"\n"
    try:
        with temporary.open("xb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(path)
    except OSError as exc:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        raise PublicationError("could not write publication receipt") from exc


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "release_directory",
        nargs="?",
        help="Validated staging directory; required unless --verify-receipt is used.",
    )
    parser.add_argument("--target-repo", default=DEFAULT_TARGET_REPO)
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Authenticate and publish; omission is always a credential-free dry run.",
    )
    parser.add_argument(
        "--acknowledge-original-data-mirror",
        action="store_true",
        help=(
            "Explicitly acknowledge publication of the byte-exact upstream "
            "CVEfixes mirror; required with --execute for complete releases."
        ),
    )
    parser.add_argument(
        "--token-env",
        default="HF_TOKEN",
        help="Name of the environment variable holding the token (never the token itself).",
    )
    parser.add_argument(
        "--receipt-out",
        type=Path,
        help="Atomically create the proposed receipt after complete verification.",
    )
    parser.add_argument(
        "--verify-receipt",
        type=Path,
        help="Read-only remote verification of an existing proposed receipt.",
    )
    parser.add_argument("--viewer-attempts", type=int, default=12)
    parser.add_argument("--viewer-delay-seconds", type=float, default=5.0)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.verify_receipt is not None:
            if (
                args.release_directory
                or args.execute
                or args.acknowledge_original_data_mirror
                or args.receipt_out
            ):
                raise PublicationError(
                    "--verify-receipt cannot be combined with publication arguments"
                )
            result = verify_receipt(
                args.verify_receipt, token_env=args.token_env
            )
        else:
            if not args.release_directory:
                raise PublicationError("release_directory is required")
            result = publish_release(
                args.release_directory,
                target_repo=args.target_repo,
                execute=args.execute,
                acknowledge_original_data_mirror=(
                    args.acknowledge_original_data_mirror
                ),
                token_env=args.token_env,
                viewer_attempts=args.viewer_attempts,
                viewer_delay_seconds=args.viewer_delay_seconds,
            )
            if args.receipt_out is not None:
                if not args.execute:
                    raise PublicationError(
                        "--receipt-out requires --execute and complete verification"
                    )
                write_receipt(result, args.receipt_out)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except PublicationError as exc:
        print(f"publication failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
