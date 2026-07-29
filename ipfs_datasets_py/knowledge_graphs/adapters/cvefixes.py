"""Read-only CVEfixes Security IR GraphRAG corpus adapter (KGP-024).

Provides a fail-closed, integrity-checked reader over the CVEfixes release
layout produced under ``lift_coding/.cvefixes-build`` (and the matching Hub
dataset ``Publicus/cvefixes-security-ir-graphrag``).

This module is the canonical in-tree port of the production query client
``scripts/ops/security_ir/query_cvefixes_security_ir.py`` (nested producer tree)
plus discovery, count/checksum/provenance validation, representative
CVE/CWE/code-unit/commit traversals, and missing/corrupt shard handling.

The adapter is strictly read-only: it never mutates release artifacts.
"""

from __future__ import annotations

import base64
from collections import defaultdict
import gc
import hashlib
import heapq
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import sys
from typing import Any, Mapping, Sequence
import unicodedata


DEFAULT_REPO_ID = "Publicus/cvefixes-security-ir-graphrag"
DEFAULT_MANIFEST = "manifest.json"
DEFAULT_CACHE_DIR = Path(
    "~/.cache/ipfs_datasets_py/cvefixes-security-ir-query"
).expanduser()

SUPPORTED_RELEASE_SCHEMAS = {
    "cvefixes-huggingface-release/v1",
    "cvefixes-huggingface-release/v2",
}
META_SCHEMA_VERSION = "cvefixes-hf-shard-meta/v1"
BM25_TOKENIZER = "cvefixes-ascii-code-nfkc-casefold/v1"

MAX_QUERY_TERMS = 64
MAX_TOP_K = 1_000
MAX_CANDIDATE_CENTROIDS = 64
MAX_VECTOR_SHARDS = 128
MAX_GRAPH_DEPTH = 8
MAX_GRAPH_NODES = 10_000
MAX_GRAPH_EDGES = 100_000
MAX_GRAPH_SHARDS = 1_024
MAX_QUERY_VECTOR_DIMENSION = 16_384

_REVISION_RE = re.compile(r"[0-9a-fA-F]{40}")
_MODEL_REVISION_RE = re.compile(r"[0-9a-f]{40}")
_SHA256_RE = re.compile(r"[0-9a-f]{64}")
_CID_RE = re.compile(r"b[a-z2-7]{58}")
_TOKEN_RE = re.compile(r"[a-z0-9]+(?:[-_./:][a-z0-9]+)*")
_TOKEN_SPLIT_RE = re.compile(r"[-_./:]")
_PART_RE = re.compile(r"part-\d{6}\.parquet")

_INDEX_PATHS = {
    "bm25_keyword_shards": "indexes/bm25_keyword_shards.parquet",
    "corpus_chunks": "indexes/corpus_chunks.parquet",
    "graph_incoming_adjacency": (
        "indexes/graph_incoming_adjacency.parquet"
    ),
    "graph_node_chunks": "indexes/graph_node_chunks.parquet",
    "graph_outgoing_adjacency": (
        "indexes/graph_outgoing_adjacency.parquet"
    ),
    "vector_chunks": "indexes/vector_chunks.parquet",
}
_DATA_PREFIXES = {
    "bm25_keyword_shards": "data/bm25/postings/",
    "corpus_chunks": "data/corpus/",
    "graph_incoming_adjacency": "data/graph/adjacency/incoming/",
    "graph_node_chunks": "data/graph/nodes/",
    "graph_outgoing_adjacency": "data/graph/adjacency/outgoing/",
    "vector_chunks": "data/vectors/",
}
_EXPECTED_KINDS = {
    "bm25_keyword_shards": {"bm25_postings"},
    "corpus_chunks": {"corpus"},
    "graph_incoming_adjacency": {"graph_incoming_adjacency"},
    "graph_node_chunks": {"graph_nodes"},
    "graph_outgoing_adjacency": {"graph_outgoing_adjacency"},
    "vector_chunks": {"vectors"},
}
_NON_OVERLAPPING_KEY_INDEXES = {
    "bm25_keyword_shards",
    "corpus_chunks",
    "graph_node_chunks",
}
_DOCUMENT_RANGE_INDEXES = {"corpus_chunks", "vector_chunks"}
_CONTENT_COLUMNS = {
    "body",
    "content",
    "library_md",
    "metadata_yaml",
    "record_json",
    "skill_md",
    "text",
}


class RemoteQueryError(RuntimeError):
    """Raised when a release, artifact, or bounded query is malformed."""


class _GraphShardBudgetReached(RuntimeError):
    """Internal signal used to stop a bounded graph walk."""


def _validate_revision(value: str) -> str:
    revision = str(value or "")
    if _REVISION_RE.fullmatch(revision) is None:
        raise RemoteQueryError(
            "revision must be an immutable 40-character Hub commit SHA"
        )
    return revision.lower()


def _safe_relative_path(value: str) -> PurePosixPath:
    path = PurePosixPath(str(value or ""))
    if (
        not value
        or path.is_absolute()
        or path.as_posix() != value
        or any(part in {"", ".", ".."} for part in path.parts)
        or "\\" in value
    ):
        raise RemoteQueryError(f"unsafe release path: {value!r}")
    return path


def _descriptor_path(value: Mapping[str, Any]) -> str:
    relative_path = value.get("relative_path")
    if not isinstance(relative_path, str):
        raise RemoteQueryError("artifact descriptor has no relative_path")
    return _safe_relative_path(relative_path).as_posix()


def _descriptor_size(value: Mapping[str, Any]) -> int:
    size = value.get("size_bytes")
    if type(size) is not int or size <= 0:
        raise RemoteQueryError("artifact descriptor has an invalid size")
    return size


def _validate_descriptor_shape(value: Mapping[str, Any]) -> None:
    _descriptor_path(value)
    _descriptor_size(value)
    sha256 = value.get("sha256")
    cid = value.get("cid")
    if not isinstance(sha256, str) or _SHA256_RE.fullmatch(sha256) is None:
        raise RemoteQueryError("artifact descriptor has an invalid SHA-256")
    if not isinstance(cid, str) or _CID_RE.fullmatch(cid) is None:
        raise RemoteQueryError("artifact descriptor has an invalid raw-file CID")


def _raw_sha256_cid(digest: bytes) -> str:
    if len(digest) != 32:
        raise RemoteQueryError("SHA-256 digest has an invalid length")
    # CIDv1 + raw codec + sha2-256 multihash.
    payload = bytes((0x01, 0x55, 0x12, 0x20)) + digest
    return "b" + base64.b32encode(payload).decode("ascii").lower().rstrip("=")


def _verify_descriptor(path: Path, value: Mapping[str, Any]) -> None:
    _validate_descriptor_shape(value)
    if path.stat().st_size != _descriptor_size(value):
        raise RemoteQueryError(f"artifact size differs: {path.name}")
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            while chunk := handle.read(8 * 1024 * 1024):
                digest.update(chunk)
    except OSError as exc:
        raise RemoteQueryError(
            f"cannot read fetched artifact: {path.name}"
        ) from exc
    raw_digest = digest.digest()
    if raw_digest.hex() != value["sha256"]:
        raise RemoteQueryError(f"artifact digest differs: {path.name}")
    if _raw_sha256_cid(raw_digest) != value["cid"]:
        raise RemoteQueryError(f"artifact CID differs: {path.name}")


class ArtifactResolver:
    """Fetch only explicitly selected files from a pinned release."""

    def __init__(
        self,
        *,
        repo_id: str,
        revision: str,
        path_prefix: str = "",
        token: str | None = None,
        cache_dir: Path = DEFAULT_CACHE_DIR,
        local_root: Path | None = None,
    ) -> None:
        self.repo_id = str(repo_id)
        if "/" not in self.repo_id or any(
            character.isspace() for character in self.repo_id
        ):
            raise RemoteQueryError("dataset repo_id is malformed")
        self.revision = _validate_revision(revision)
        self.path_prefix = path_prefix.strip("/")
        if self.path_prefix:
            _safe_relative_path(self.path_prefix)
        self._token = token
        self.cache_dir = cache_dir.expanduser().resolve()
        self.local_root = (
            local_root.expanduser().resolve()
            if local_root is not None
            else None
        )
        self.fetched: dict[str, int] = {}
        self._parquet_cache: dict[
            tuple[str, tuple[str, ...] | None], Any
        ] = {}

    def path(
        self,
        relative_path: str,
        *,
        descriptor: Mapping[str, Any] | None = None,
    ) -> Path:
        safe = _safe_relative_path(relative_path)
        if self.local_root is not None:
            path = self.local_root.joinpath(*safe.parts)
            try:
                path.resolve().relative_to(self.local_root)
            except ValueError as exc:
                raise RemoteQueryError("local path escapes release root") from exc
            if path.is_symlink() or not path.is_file():
                raise RemoteQueryError(
                    f"release file is missing: {safe.as_posix()}"
                )
        else:
            try:
                from huggingface_hub import hf_hub_download
            except ImportError as exc:
                raise RemoteQueryError(
                    "huggingface_hub is required for remote queries"
                ) from exc
            filename = (
                f"{self.path_prefix}/{safe.as_posix()}"
                if self.path_prefix
                else safe.as_posix()
            )
            try:
                path = Path(
                    hf_hub_download(
                        repo_id=self.repo_id,
                        filename=filename,
                        repo_type="dataset",
                        revision=self.revision,
                        token=self._token,
                        cache_dir=str(self.cache_dir),
                    )
                )
            except Exception:
                # Hub exceptions may include request details. Keep the public
                # failure deterministic and never echo headers or credentials.
                raise RemoteQueryError(
                    f"failed to fetch pinned artifact: {safe.as_posix()}"
                ) from None
        if descriptor is not None:
            if _descriptor_path(descriptor) != safe.as_posix():
                raise RemoteQueryError("artifact descriptor path differs")
            _verify_descriptor(path, descriptor)
        self.fetched[safe.as_posix()] = path.stat().st_size
        return path

    def json(self, relative_path: str) -> dict[str, Any]:
        try:
            value = json.loads(
                self.path(relative_path).read_text(encoding="utf-8")
            )
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise RemoteQueryError(
                f"JSON artifact is malformed: {relative_path}"
            ) from exc
        if not isinstance(value, dict):
            raise RemoteQueryError(
                f"JSON artifact must be an object: {relative_path}"
            )
        return value

    def parquet(
        self,
        descriptor: Mapping[str, Any],
        *,
        columns: Sequence[str] | None = None,
    ) -> Any:
        try:
            import pyarrow.parquet as pq
        except ImportError as exc:
            raise RemoteQueryError(
                "pyarrow is required for remote Parquet queries"
            ) from exc
        relative_path = _descriptor_path(descriptor)
        key = (
            relative_path,
            tuple(columns) if columns is not None else None,
        )
        cached = self._parquet_cache.get(key)
        if cached is not None:
            return cached
        try:
            table = pq.read_table(
                self.path(relative_path, descriptor=descriptor),
                columns=list(columns) if columns is not None else None,
            )
        except RemoteQueryError:
            raise
        except Exception:
            raise RemoteQueryError(
                f"cannot decode Parquet artifact: {relative_path}"
            ) from None
        expected_rows = descriptor.get("row_count")
        if expected_rows is not None and (
            type(expected_rows) is not int
            or expected_rows <= 0
            or table.num_rows != expected_rows
        ):
            raise RemoteQueryError(
                f"Parquet row count differs: {relative_path}"
            )
        self._parquet_cache[key] = table
        return table

    def trace(self) -> dict[str, Any]:
        files = [
            {"relative_path": path, "size_bytes": size}
            for path, size in sorted(self.fetched.items())
        ]
        return {
            "file_count": len(files),
            "files": files,
            "total_file_bytes": sum(item["size_bytes"] for item in files),
        }


def _validate_meta_rows(
    name: str,
    rows: Sequence[Mapping[str, Any]],
) -> None:
    if name not in _DATA_PREFIXES or not rows:
        raise RemoteQueryError(f"release index is empty or unsupported: {name}")
    paths: set[str] = set()
    shard_ids: set[int] = set()
    prefix = _DATA_PREFIXES[name]
    expected_kinds = _EXPECTED_KINDS[name]
    for row in rows:
        _validate_descriptor_shape(row)
        path = _descriptor_path(row)
        suffix = path[len(prefix) :] if path.startswith(prefix) else ""
        if not suffix or _PART_RE.fullmatch(suffix) is None:
            raise RemoteQueryError(
                f"{name} contains an unexpected data path"
            )
        if path in paths:
            raise RemoteQueryError(f"{name} contains a duplicate shard path")
        paths.add(path)
        shard_id = row.get("shard_id")
        if type(shard_id) is not int or shard_id < 0 or shard_id in shard_ids:
            raise RemoteQueryError(f"{name} has an invalid shard_id")
        shard_ids.add(shard_id)
        if row.get("schema_version") != META_SCHEMA_VERSION:
            raise RemoteQueryError(f"{name} has an unsupported meta schema")
        if row.get("kind") not in expected_kinds:
            raise RemoteQueryError(f"{name} has an unexpected shard kind")
        if type(row.get("row_count")) is not int or row["row_count"] <= 0:
            raise RemoteQueryError(f"{name} has an invalid row count")
        first_key = row.get("first_key")
        last_key = row.get("last_key")
        if (
            not isinstance(first_key, str)
            or not first_key
            or not isinstance(last_key, str)
            or not last_key
        ):
            raise RemoteQueryError(f"{name} has an invalid key range")
        start = row.get("start_document_index")
        end = row.get("end_document_index")
        if name in _DOCUMENT_RANGE_INDEXES:
            if (
                type(start) is not int
                or type(end) is not int
                or start < 0
                or end < start
            ):
                raise RemoteQueryError(
                    f"{name} has an invalid document range"
                )
        elif start != -1 or end != -1:
            raise RemoteQueryError(
                f"{name} must not declare document ranges"
            )
        if "adjacency" in name:
            expected_direction = (
                "incoming" if "incoming" in name else "outgoing"
            )
            if row.get("direction") != expected_direction:
                raise RemoteQueryError(
                    f"{name} has an invalid adjacency direction"
                )
    if shard_ids != set(range(len(rows))):
        raise RemoteQueryError(f"{name} shard IDs are not contiguous")
    if name in _NON_OVERLAPPING_KEY_INDEXES:
        by_range = sorted(
            rows, key=lambda item: (str(item["first_key"]), int(item["shard_id"]))
        )
        for left, right in zip(by_range, by_range[1:]):
            if str(left["last_key"]) >= str(right["first_key"]):
                raise RemoteQueryError(
                    f"{name} contains overlapping key ranges"
                )


def _require_columns(table: Any, columns: Sequence[str], *, label: str) -> None:
    missing = [column for column in columns if column not in table.column_names]
    if missing:
        raise RemoteQueryError(
            f"{label} is missing required columns: {', '.join(missing)}"
        )


def _validate_loaded_shard(
    name: str,
    descriptor: Mapping[str, Any],
    table: Any,
) -> None:
    path = _descriptor_path(descriptor)
    if table.num_rows != int(descriptor["row_count"]) or table.num_rows <= 0:
        raise RemoteQueryError(f"shard row count differs: {path}")
    if name == "bm25_keyword_shards":
        key_column = "term"
    elif name in {
        "graph_incoming_adjacency",
        "graph_node_chunks",
        "graph_outgoing_adjacency",
    }:
        key_column = "node_cid"
    elif name == "vector_chunks":
        key_column = "entry_cid"
    else:
        key_column = (
            "entry_cid"
            if "entry_cid" in table.column_names
            else "record_id"
        )
    _require_columns(table, [key_column], label=path)
    keys = [str(value) for value in table[key_column].to_pylist()]
    if (
        not keys
        or keys[0] != str(descriptor["first_key"])
        or keys[-1] != str(descriptor["last_key"])
    ):
        raise RemoteQueryError(f"shard key range differs: {path}")

    start = int(descriptor["start_document_index"])
    end = int(descriptor["end_document_index"])
    if name in _DOCUMENT_RANGE_INDEXES:
        if "document_index" not in table.column_names:
            if name != "corpus_chunks":
                raise RemoteQueryError(f"document index is missing: {path}")
            # Legacy corpus rows can be indexed by stable row offset.
            if end - start + 1 != table.num_rows:
                raise RemoteQueryError(f"document range differs: {path}")
        else:
            document_ids = [
                int(value) for value in table["document_index"].to_pylist()
            ]
            if (
                len(document_ids) != len(set(document_ids))
                or min(document_ids) != start
                or max(document_ids) != end
            ):
                raise RemoteQueryError(f"document range differs: {path}")
            if name == "corpus_chunks" and document_ids != list(
                range(start, end + 1)
            ):
                raise RemoteQueryError(
                    f"corpus document range is not contiguous: {path}"
                )

    if "adjacency" in name:
        _require_columns(table, ["direction"], label=path)
        expected_direction = (
            "incoming" if "incoming" in name else "outgoing"
        )
        if set(table["direction"].to_pylist()) != {expected_direction}:
            raise RemoteQueryError(f"adjacency direction differs: {path}")


def _json_value(value: Any) -> Any:
    if isinstance(value, bytes):
        return value.hex()
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return value


def _tokenize(text: str) -> list[str]:
    normalized = unicodedata.normalize("NFKC", str(text or "")).casefold()
    seen: set[str] = set()
    result: list[str] = []
    for match in _TOKEN_RE.findall(normalized):
        tokens = [match]
        if _TOKEN_SPLIT_RE.search(match):
            tokens.extend(
                part for part in _TOKEN_SPLIT_RE.split(match) if part
            )
        for token in tokens:
            if token not in seen:
                seen.add(token)
                result.append(token)
                if len(result) >= MAX_QUERY_TERMS:
                    return result
    return result


def _validate_top_k(value: int) -> None:
    if isinstance(value, bool) or not 1 <= int(value) <= MAX_TOP_K:
        raise RemoteQueryError(f"top_k must be between 1 and {MAX_TOP_K}")


def _bm25_term_score(
    term_frequency: float,
    document_length: int,
    *,
    idf: float,
    average_document_length: float,
    k1: float,
    b: float,
) -> float:
    denominator = term_frequency + k1 * (
        1.0
        - b
        + b * float(document_length) / max(average_document_length, 1.0)
    )
    if denominator <= 0:
        raise RemoteQueryError("BM25 posting has an invalid denominator")
    return idf * ((k1 + 1.0) * term_frequency) / denominator


def _select_keyword_shards(
    meta_rows: Sequence[Mapping[str, Any]],
    terms: Sequence[str],
) -> dict[str, Mapping[str, Any]]:
    selected: dict[str, Mapping[str, Any]] = {}
    for term in terms:
        matches = [
            row
            for row in meta_rows
            if str(row["first_key"]) <= term <= str(row["last_key"])
        ]
        if len(matches) > 1:
            raise RemoteQueryError(
                f"overlapping BM25 keyword shard ranges for {term!r}"
            )
        if matches:
            selected[term] = matches[0]
    return selected


def _vector_routing_groups(
    rows: Sequence[Mapping[str, Any]],
    *,
    dimension: int,
    max_shards_per_centroid: int,
) -> list[dict[str, Any]]:
    grouped: dict[int, list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        cluster_id = row.get("cluster_id")
        chunk = row.get("chunk_in_cluster")
        shard_count = row.get("centroid_shard_count")
        centroid = row.get("centroid")
        if (
            type(cluster_id) is not int
            or cluster_id < 0
            or type(chunk) is not int
            or chunk < 0
            or type(shard_count) is not int
            or not 1 <= shard_count <= max_shards_per_centroid
            or not isinstance(centroid, Sequence)
            or isinstance(centroid, (str, bytes))
            or len(centroid) != dimension
        ):
            raise RemoteQueryError("vector centroid meta-index is malformed")
        grouped[cluster_id].append(row)
    result = []
    for cluster_id in sorted(grouped):
        shards = sorted(
            grouped[cluster_id], key=lambda row: int(row["chunk_in_cluster"])
        )
        try:
            centroid = [float(value) for value in shards[0]["centroid"]]
            remaining_centroids = [
                [float(value) for value in row["centroid"]]
                for row in shards[1:]
            ]
        except (TypeError, ValueError, OverflowError):
            raise RemoteQueryError(
                "vector centroid meta-index is malformed"
            ) from None
        if (
            [int(row["chunk_in_cluster"]) for row in shards]
            != list(range(len(shards)))
            or any(
                int(row["centroid_shard_count"]) != len(shards)
                for row in shards
            )
            or any(value != centroid for value in remaining_centroids)
            or any(not math.isfinite(value) for value in centroid)
        ):
            raise RemoteQueryError(
                f"vector centroid {cluster_id} has malformed shard pointers"
            )
        norm = math.sqrt(sum(value * value for value in centroid))
        if not math.isfinite(norm) or norm == 0:
            raise RemoteQueryError("vector routing centroid is zero or non-finite")
        result.append(
            {
                "centroid": [value / norm for value in centroid],
                "cluster_id": cluster_id,
                "shards": shards,
            }
        )
    if not result:
        raise RemoteQueryError("vector routing meta-index is empty")
    return result


class CVEfixesRemoteIndex:
    """BM25, vector, and bounded graph queries over one pinned release."""

    def __init__(
        self,
        resolver: ArtifactResolver,
        *,
        manifest_path: str = DEFAULT_MANIFEST,
    ) -> None:
        self.resolver = resolver
        self.manifest = resolver.json(manifest_path)
        if self.manifest.get("schema_version") not in SUPPORTED_RELEASE_SCHEMAS:
            raise RemoteQueryError("unsupported CVEfixes release manifest")
        primary_key = self.manifest.get("primary_key")
        if primary_key not in {None, "entry_cid"}:
            raise RemoteQueryError(
                "CVEfixes release primary key must be entry_cid"
            )
        indexes = self.manifest.get("indexes")
        if not isinstance(indexes, Mapping):
            raise RemoteQueryError("release index descriptors are missing")
        self.indexes = dict(indexes)
        self._meta_cache: dict[str, list[dict[str, Any]]] = {}

    def _meta_rows(self, name: str) -> list[dict[str, Any]]:
        cached = self._meta_cache.get(name)
        if cached is not None:
            return cached
        descriptor = self.indexes.get(name)
        if not isinstance(descriptor, Mapping):
            raise RemoteQueryError(f"release index is missing: {name}")
        if _descriptor_path(descriptor) != _INDEX_PATHS.get(name):
            raise RemoteQueryError(f"release index path differs: {name}")
        table = self.resolver.parquet(descriptor)
        rows = [dict(row) for row in table.to_pylist()]
        _validate_meta_rows(name, rows)
        self._meta_cache[name] = rows
        return rows

    def _read_shard(
        self,
        name: str,
        descriptor: Mapping[str, Any],
    ) -> Any:
        table = self.resolver.parquet(descriptor)
        _validate_loaded_shard(name, descriptor, table)
        return table

    def _hydrate(
        self,
        document_ids: Sequence[int],
        *,
        include_content: bool,
    ) -> dict[int, dict[str, Any]]:
        if not document_ids:
            return {}
        meta = self._meta_rows("corpus_chunks")
        by_path: dict[str, set[int]] = defaultdict(set)
        descriptors: dict[str, Mapping[str, Any]] = {}
        for document_id in sorted(set(int(value) for value in document_ids)):
            matches = [
                row
                for row in meta
                if int(row["start_document_index"])
                <= document_id
                <= int(row["end_document_index"])
            ]
            if len(matches) != 1:
                raise RemoteQueryError(
                    f"corpus pointer is not unique for document {document_id}"
                )
            path = str(matches[0]["relative_path"])
            by_path[path].add(document_id)
            descriptors[path] = matches[0]
        result: dict[int, dict[str, Any]] = {}
        for path, wanted in sorted(by_path.items()):
            descriptor = descriptors[path]
            table = self._read_shard("corpus_chunks", descriptor)
            rows = table.to_pylist()
            start = int(descriptor["start_document_index"])
            for offset, row in enumerate(rows):
                document_id = int(row.get("document_index", start + offset))
                if document_id not in wanted:
                    continue
                public = {
                    str(key): _json_value(value)
                    for key, value in row.items()
                    if include_content or str(key) not in _CONTENT_COLUMNS
                }
                public["document_index"] = document_id
                if "entry_cid" not in public and "record_id" in public:
                    public["entry_cid"] = public["record_id"]
                result[document_id] = public
        return result

    def _result(
        self,
        mode: str,
        query: str,
        results: Sequence[Mapping[str, Any]],
        diagnostics: Mapping[str, Any],
    ) -> dict[str, Any]:
        return {
            "dataset_repo_id": self.resolver.repo_id,
            "hub_revision": self.resolver.revision,
            "diagnostics": dict(diagnostics),
            "fetch_trace": self.resolver.trace(),
            "mode": mode,
            "query": query,
            "result_count": len(results),
            "results": list(results),
        }

    def bm25(
        self,
        query: str,
        *,
        top_k: int,
        include_content: bool = True,
    ) -> dict[str, Any]:
        _validate_top_k(top_k)
        config_value = self.manifest.get("bm25")
        if not isinstance(config_value, Mapping):
            raise RemoteQueryError("release BM25 configuration is missing")
        config = dict(config_value)
        if config.get("tokenizer") not in {None, BM25_TOKENIZER}:
            raise RemoteQueryError("release BM25 tokenizer is unsupported")
        try:
            average_length = float(config["average_document_length"])
            k1 = float(config["k1"])
            b = float(config["b"])
            title_weight = float(config["title_weight"])
            body_weight = float(config["body_weight"])
            max_query_terms = int(
                config.get("max_query_terms", MAX_QUERY_TERMS)
            )
        except (KeyError, TypeError, ValueError, OverflowError):
            raise RemoteQueryError("release BM25 configuration is malformed") from None
        if (
            not all(
                math.isfinite(value)
                for value in (
                    average_length,
                    k1,
                    b,
                    title_weight,
                    body_weight,
                )
            )
            or average_length <= 0
            or k1 <= 0
            or not 0 <= b <= 1
            or title_weight <= 0
            or body_weight <= 0
            or not 1 <= max_query_terms <= MAX_QUERY_TERMS
        ):
            raise RemoteQueryError("release BM25 configuration is malformed")
        terms = _tokenize(query)[:max_query_terms]
        if not terms:
            return self._result("bm25", query, [], {"query_terms": []})
        selected = _select_keyword_shards(
            self._meta_rows("bm25_keyword_shards"), terms
        )
        rows_by_path: dict[str, set[str]] = defaultdict(set)
        descriptors: dict[str, Mapping[str, Any]] = {}
        for term, row in selected.items():
            path = str(row["relative_path"])
            rows_by_path[path].add(term)
            descriptors[path] = row

        scores: dict[int, float] = defaultdict(float)
        matched: dict[int, set[str]] = defaultdict(set)
        posting_candidates: set[int] = set()
        for path, wanted_terms in sorted(rows_by_path.items()):
            table = self._read_shard(
                "bm25_keyword_shards", descriptors[path]
            )
            _require_columns(
                table,
                [
                    "body_frequencies",
                    "document_indices",
                    "document_lengths",
                    "idf",
                    "term",
                    "title_frequencies",
                ],
                label=path,
            )
            for row in table.to_pylist():
                term = str(row["term"])
                if term not in wanted_terms:
                    continue
                arrays = [
                    row["document_indices"],
                    row["title_frequencies"],
                    row["body_frequencies"],
                    row["document_lengths"],
                ]
                if not arrays[0] or any(
                    len(values) != len(arrays[0]) for values in arrays[1:]
                ):
                    raise RemoteQueryError(
                        f"unaligned BM25 posting arrays for {term!r}"
                    )
                try:
                    idf = float(row["idf"])
                except (TypeError, ValueError, OverflowError):
                    raise RemoteQueryError(
                        "BM25 posting has an invalid IDF"
                    ) from None
                if not math.isfinite(idf) or idf < 0:
                    raise RemoteQueryError("BM25 posting has an invalid IDF")
                for document_id, title_tf, body_tf, document_length in zip(
                    *arrays
                ):
                    try:
                        document_id = int(document_id)
                        title_tf = int(title_tf)
                        body_tf = int(body_tf)
                        document_length = int(document_length)
                    except (TypeError, ValueError, OverflowError):
                        raise RemoteQueryError(
                            "BM25 posting values are malformed"
                        ) from None
                    if (
                        document_id < 0
                        or title_tf < 0
                        or body_tf < 0
                        or title_tf + body_tf <= 0
                        or document_length <= 0
                    ):
                        raise RemoteQueryError("BM25 posting values are malformed")
                    weighted_tf = (
                        title_weight * title_tf + body_weight * body_tf
                    )
                    scores[document_id] += _bm25_term_score(
                        weighted_tf,
                        document_length,
                        idf=idf,
                        average_document_length=average_length,
                        k1=k1,
                        b=b,
                    )
                    matched[document_id].add(term)
                    posting_candidates.add(document_id)
        ranked = heapq.nlargest(
            top_k, scores.items(), key=lambda item: (item[1], -item[0])
        )
        hydrated = self._hydrate(
            [document_id for document_id, _ in ranked],
            include_content=include_content,
        )
        results = []
        for document_id, score in ranked:
            row = hydrated.get(document_id)
            if row is None:
                raise RemoteQueryError(
                    f"corpus pointer is missing for document {document_id}"
                )
            results.append(
                {
                    **row,
                    "authority": "context_only",
                    "matched_terms": sorted(matched[document_id]),
                    "proof_authority": False,
                    "score": score,
                }
            )
        return self._result(
            "bm25",
            query,
            results,
            {
                "candidate_documents": len(posting_candidates),
                "keyword_shards_fetched": len(rows_by_path),
                "query_terms": terms,
            },
        )

    def vector(
        self,
        query: str,
        *,
        top_k: int,
        query_vector: Sequence[float],
        candidate_centroids: int | None = None,
        max_vector_shards: int = 8,
        include_content: bool = True,
        allow_exhaustive: bool = False,
    ) -> dict[str, Any]:
        _validate_top_k(top_k)
        try:
            import numpy as np
        except ImportError as exc:
            raise RemoteQueryError("numpy is required for vector search") from exc
        config_value = self.manifest.get("vector")
        if not isinstance(config_value, Mapping):
            raise RemoteQueryError("release vector configuration is missing")
        config = dict(config_value)
        try:
            dimension = int(config["dimension"])
            max_shards_per_centroid = int(
                config.get("max_shards_per_centroid", 2)
            )
        except (KeyError, TypeError, ValueError, OverflowError):
            raise RemoteQueryError("release vector configuration is malformed") from None
        if not 1 <= dimension <= MAX_QUERY_VECTOR_DIMENSION:
            raise RemoteQueryError("release vector dimension is out of bounds")
        if not 1 <= max_shards_per_centroid <= 2:
            raise RemoteQueryError(
                "release vector centroid fan-out exceeds the client bound"
            )
        if not 1 <= max_vector_shards <= MAX_VECTOR_SHARDS:
            raise RemoteQueryError(
                f"max_vector_shards must be between 1 and {MAX_VECTOR_SHARDS}"
            )
        try:
            query_array = np.asarray(query_vector, dtype=np.float32)
        except (TypeError, ValueError, OverflowError):
            raise RemoteQueryError(
                "query vector contains invalid values"
            ) from None
        if query_array.shape != (dimension,) or not np.isfinite(query_array).all():
            raise RemoteQueryError(
                f"query vector must contain {dimension} finite values"
            )
        query_norm = float(np.linalg.norm(query_array))
        if not math.isfinite(query_norm) or query_norm == 0:
            raise RemoteQueryError("query vector must be non-zero")
        query_array /= query_norm

        meta = self._meta_rows("vector_chunks")
        model_name = str(config.get("model_name") or "")
        model_id = str(config.get("model_id") or "")
        model_revision = str(config.get("model_revision") or "")
        model_config_cid = str(config.get("model_config_cid") or "")
        try:
            neutral_rows = int(config.get("neutral_rows", 0))
        except (TypeError, ValueError, OverflowError):
            raise RemoteQueryError(
                "release vector model binding is malformed"
            ) from None
        if (
            not model_name
            or not model_id
            or not model_revision
            or model_name != f"{model_id}@{model_revision}"
            or _CID_RE.fullmatch(model_config_cid) is None
            or config.get("searchable") is not True
            or neutral_rows != 0
        ):
            raise RemoteQueryError(
                "release vector model binding is incomplete or non-searchable"
            )
        groups = _vector_routing_groups(
            meta,
            dimension=dimension,
            max_shards_per_centroid=max_shards_per_centroid,
        )
        try:
            probes = (
                int(candidate_centroids)
                if candidate_centroids is not None
                else int(config.get("default_probe_centroids", 4))
            )
        except (TypeError, ValueError, OverflowError):
            raise RemoteQueryError(
                "candidate_centroids is malformed"
            ) from None
        if not 1 <= probes <= MAX_CANDIDATE_CENTROIDS:
            raise RemoteQueryError(
                "candidate_centroids exceeds the client bound"
            )
        probes = min(probes, len(groups))
        if probes == len(groups) and len(groups) > 1 and not allow_exhaustive:
            raise RemoteQueryError(
                "centroid selection would fetch the full vector index; "
                "pass --allow-exhaustive explicitly"
            )
        centroid_matrix = np.asarray(
            [group["centroid"] for group in groups], dtype=np.float32
        )
        centroid_scores = centroid_matrix @ query_array
        selected_group_indices = np.argsort(
            -centroid_scores, kind="stable"
        )[:probes]
        selected_groups = [groups[int(index)] for index in selected_group_indices]
        selected_shards = [
            row for group in selected_groups for row in group["shards"]
        ]
        if len(selected_shards) > max_vector_shards:
            raise RemoteQueryError(
                "selected centroids exceed max_vector_shards"
            )

        heap: list[tuple[float, int, dict[str, Any]]] = []
        candidate_rows = 0
        for descriptor in selected_shards:
            table = self._read_shard("vector_chunks", descriptor)
            _require_columns(
                table,
                [
                    "document_index",
                    "embedding",
                    "entry_cid",
                    "has_embedding",
                    "model_config_cid",
                    "model_id",
                    "model_revision",
                ],
                label=_descriptor_path(descriptor),
            )
            if descriptor.get("dimension") not in {None, dimension}:
                raise RemoteQueryError("vector shard dimension binding differs")
            if descriptor.get("model_name") not in {None, model_name}:
                raise RemoteQueryError("vector shard model binding differs")
            if (
                set(table["has_embedding"].to_pylist()) != {True}
                or set(table["model_id"].to_pylist()) != {model_id}
                or set(table["model_revision"].to_pylist())
                != {model_revision}
                or set(table["model_config_cid"].to_pylist())
                != {model_config_cid}
            ):
                raise RemoteQueryError("vector data model binding differs")
            try:
                matrix = np.asarray(
                    table["embedding"].to_pylist(), dtype=np.float32
                )
            except (TypeError, ValueError, OverflowError):
                raise RemoteQueryError("vector shard embeddings are malformed") from None
            if (
                matrix.shape != (table.num_rows, dimension)
                or not np.isfinite(matrix).all()
            ):
                raise RemoteQueryError("vector shard embeddings are malformed")
            norms = np.linalg.norm(matrix, axis=1)
            if not np.isfinite(norms).all() or np.any(norms == 0):
                raise RemoteQueryError("vector shard contains zero embeddings")
            shard_scores = (matrix / norms[:, None]) @ query_array
            candidate_rows += table.num_rows
            for row, score in zip(
                table.drop(["embedding"]).to_pylist(), shard_scores
            ):
                document_id = int(row["document_index"])
                item = (float(score), -document_id, dict(row))
                if len(heap) < top_k:
                    heapq.heappush(heap, item)
                elif item[:2] > heap[0][:2]:
                    heapq.heapreplace(heap, item)
        hits = sorted(heap, key=lambda item: item[:2], reverse=True)
        hydrated = self._hydrate(
            [int(row["document_index"]) for _, _, row in hits],
            include_content=include_content,
        )
        results = []
        for score, _, pointer in hits:
            document_id = int(pointer["document_index"])
            row = hydrated.get(document_id)
            if row is None:
                raise RemoteQueryError(
                    f"corpus pointer is missing for document {document_id}"
                )
            results.append(
                {
                    **row,
                    "authority": "context_only",
                    "proof_authority": False,
                    "score": score,
                    "vector_chunk_id": str(pointer.get("chunk_id") or ""),
                }
            )
        return self._result(
            "vector",
            query,
            results,
            {
                "candidate_centroid_ids": [
                    int(group["cluster_id"]) for group in selected_groups
                ],
                "candidate_centroids": len(selected_groups),
                "candidate_shard_ids": [
                    int(row["shard_id"]) for row in selected_shards
                ],
                "candidate_rows": candidate_rows,
                "dimension": dimension,
                "model_name": model_name,
                "vector_shards_fetched": len(selected_shards),
            },
        )

    def _graph_nodes(
        self, node_cids: Sequence[str]
    ) -> dict[str, dict[str, Any]]:
        wanted = sorted(set(str(value) for value in node_cids))
        if not wanted:
            return {}
        meta = self._meta_rows("graph_node_chunks")
        rows_by_path: dict[str, set[str]] = defaultdict(set)
        descriptors: dict[str, Mapping[str, Any]] = {}
        for node_cid in wanted:
            matches = [
                row
                for row in meta
                if str(row["first_key"]) <= node_cid <= str(row["last_key"])
            ]
            if len(matches) > 1:
                raise RemoteQueryError(
                    f"overlapping graph node ranges for {node_cid!r}"
                )
            if matches:
                path = str(matches[0]["relative_path"])
                rows_by_path[path].add(node_cid)
                descriptors[path] = matches[0]
        result: dict[str, dict[str, Any]] = {}
        for path, selected in sorted(rows_by_path.items()):
            table = self._read_shard("graph_node_chunks", descriptors[path])
            for row in table.to_pylist():
                node_cid = str(row["node_cid"])
                if node_cid in selected:
                    result[node_cid] = {
                        str(key): _json_value(value)
                        for key, value in row.items()
                    }
        return result

    def graph_node(self, node_cid: str) -> dict[str, Any]:
        _validate_graph_key(node_cid, name="node_cid")
        nodes = self._graph_nodes([node_cid])
        return self._result(
            "graph_node",
            node_cid,
            [nodes[node_cid]] if node_cid in nodes else [],
            {"found": node_cid in nodes},
        )

    def _graph_adjacency_edges(
        self,
        node_cid: str,
        *,
        direction: str,
        limit: int,
        edge_types: set[str],
        used_paths: set[str],
        max_shards: int,
    ) -> tuple[list[dict[str, Any]], int]:
        index_name = f"graph_{direction}_adjacency"
        meta = self._meta_rows(index_name)
        descriptors = sorted(
            (
                row
                for row in meta
                if str(row["first_key"]) <= node_cid <= str(row["last_key"])
            ),
            key=lambda row: int(row["shard_id"]),
        )
        edges: list[dict[str, Any]] = []
        total_neighbors = 0
        for descriptor in descriptors:
            path = str(descriptor["relative_path"])
            if path not in used_paths and len(used_paths) >= max_shards:
                raise _GraphShardBudgetReached
            used_paths.add(path)
            table = self._read_shard(index_name, descriptor)
            _require_columns(
                table,
                [
                    "direction",
                    "edge_cids",
                    "edge_types",
                    "neighbor_cids",
                    "neighbor_count",
                    "neighbor_node_types",
                    "node_cid",
                    "page_index",
                    "retrieval_methods",
                    "scores",
                    "total_neighbor_count",
                ],
                label=path,
            )
            rows = sorted(
                (
                    row
                    for row in table.to_pylist()
                    if str(row["node_cid"]) == node_cid
                ),
                key=lambda row: int(row["page_index"]),
            )
            for row in rows:
                total_neighbors = max(
                    total_neighbors, int(row["total_neighbor_count"])
                )
                arrays = [
                    row["edge_cids"],
                    row["edge_types"],
                    row["neighbor_cids"],
                    row["neighbor_node_types"],
                    row["retrieval_methods"],
                    row["scores"],
                ]
                count = int(row["neighbor_count"])
                if (
                    count < 0
                    or any(len(values) != count for values in arrays)
                    or row["direction"] != direction
                ):
                    raise RemoteQueryError(
                        f"{direction} adjacency row is malformed"
                    )
                for (
                    edge_cid,
                    edge_type,
                    neighbor_cid,
                    neighbor_node_type,
                    retrieval_method,
                    score,
                ) in zip(*arrays):
                    edge_type = str(edge_type)
                    if edge_types and edge_type not in edge_types:
                        continue
                    try:
                        numeric_score = (
                            None if score is None else float(score)
                        )
                    except (TypeError, ValueError, OverflowError):
                        raise RemoteQueryError(
                            f"{direction} adjacency score is malformed"
                        ) from None
                    if numeric_score is not None and not math.isfinite(
                        numeric_score
                    ):
                        raise RemoteQueryError(
                            f"{direction} adjacency score is non-finite"
                        )
                    neighbor_cid = str(neighbor_cid)
                    edges.append(
                        {
                            "direction": direction,
                            "edge_cid": str(edge_cid),
                            "edge_type": edge_type,
                            "neighbor_cid": neighbor_cid,
                            "neighbor_node_type": str(neighbor_node_type),
                            "retrieval_method": str(retrieval_method),
                            "score": numeric_score,
                            "source_cid": (
                                node_cid
                                if direction == "outgoing"
                                else neighbor_cid
                            ),
                            "target_cid": (
                                neighbor_cid
                                if direction == "outgoing"
                                else node_cid
                            ),
                        }
                    )
                    if len(edges) >= limit:
                        return edges, total_neighbors
        return edges, total_neighbors

    def graph_neighbors(
        self,
        node_cid: str,
        *,
        direction: str,
        limit: int,
        offset: int = 0,
        edge_types: Sequence[str] = (),
        hydrate: bool = False,
        max_shards: int = 64,
    ) -> dict[str, Any]:
        _validate_graph_key(node_cid, name="node_cid")
        _validate_graph_bounds(limit=limit, offset=offset, max_shards=max_shards)
        directions = _graph_directions(direction)
        wanted = {str(value).strip() for value in edge_types if str(value).strip()}
        used_paths: set[str] = set()
        candidates: list[dict[str, Any]] = []
        totals: dict[str, int] = {}
        try:
            for resolved_direction in directions:
                edges, total = self._graph_adjacency_edges(
                    node_cid,
                    direction=resolved_direction,
                    limit=limit + offset,
                    edge_types=wanted,
                    used_paths=used_paths,
                    max_shards=max_shards,
                )
                candidates.extend(edges)
                totals[resolved_direction] = total
        except _GraphShardBudgetReached as exc:
            raise RemoteQueryError(
                "graph neighbor query exceeded max_shards"
            ) from exc
        candidates.sort(key=_graph_edge_order_key)
        selected = candidates[offset : offset + limit]
        result = self._result(
            "graph_neighbors",
            node_cid,
            selected,
            {
                "adjacency_shards_fetched": len(used_paths),
                "direction": direction,
                "edge_types": sorted(wanted),
                "limit": limit,
                "offset": offset,
                "total_neighbors_by_direction": totals,
            },
        )
        if hydrate:
            node_ids = [node_cid]
            node_ids.extend(str(edge["neighbor_cid"]) for edge in selected)
            nodes = self._graph_nodes(node_ids)
            result["nodes"] = [nodes[cid] for cid in sorted(nodes)]
        return result

    def graph_walk(
        self,
        start_node_cid: str,
        *,
        direction: str,
        max_depth: int,
        max_nodes: int,
        max_edges: int,
        per_node_limit: int,
        max_shards: int,
        edge_types: Sequence[str] = (),
        hydrate: bool = False,
    ) -> dict[str, Any]:
        _validate_graph_key(start_node_cid, name="start_node_cid")
        if not 0 <= max_depth <= MAX_GRAPH_DEPTH:
            raise RemoteQueryError(
                f"max_depth must be between 0 and {MAX_GRAPH_DEPTH}"
            )
        if not 1 <= max_nodes <= MAX_GRAPH_NODES:
            raise RemoteQueryError(
                f"max_nodes must be between 1 and {MAX_GRAPH_NODES}"
            )
        if not 1 <= max_edges <= MAX_GRAPH_EDGES:
            raise RemoteQueryError(
                f"max_edges must be between 1 and {MAX_GRAPH_EDGES}"
            )
        _validate_graph_bounds(
            limit=per_node_limit, offset=0, max_shards=max_shards
        )
        directions = _graph_directions(direction)
        wanted = {str(value).strip() for value in edge_types if str(value).strip()}
        start = self._graph_nodes([start_node_cid])
        if start_node_cid not in start:
            return {
                "dataset_repo_id": self.resolver.repo_id,
                "hub_revision": self.resolver.revision,
                "diagnostics": {"found": False},
                "edges": [],
                "fetch_trace": self.resolver.trace(),
                "mode": "graph_walk",
                "nodes": [],
                "start_node_cid": start_node_cid,
            }
        visited = {start_node_cid: 0}
        node_types = {
            start_node_cid: str(start[start_node_cid].get("node_type") or "")
        }
        frontier = [start_node_cid]
        traversed_edges: list[dict[str, Any]] = []
        seen_edges: set[tuple[str, str]] = set()
        used_paths: set[str] = set()
        stop_reason = "max_depth" if max_depth == 0 else "frontier_exhausted"
        for depth in range(max_depth):
            next_frontier: list[str] = []
            for node_cid in frontier:
                candidates: list[dict[str, Any]] = []
                try:
                    for resolved_direction in directions:
                        edges, _ = self._graph_adjacency_edges(
                            node_cid,
                            direction=resolved_direction,
                            limit=per_node_limit,
                            edge_types=wanted,
                            used_paths=used_paths,
                            max_shards=max_shards,
                        )
                        candidates.extend(edges)
                except _GraphShardBudgetReached:
                    stop_reason = "max_shards"
                    next_frontier = []
                    break
                candidates.sort(key=_graph_edge_order_key)
                for edge in candidates[:per_node_limit]:
                    identity = (str(edge["edge_cid"]), str(edge["direction"]))
                    if identity in seen_edges:
                        continue
                    neighbor = str(edge["neighbor_cid"])
                    if neighbor not in visited and len(visited) >= max_nodes:
                        stop_reason = "max_nodes"
                        break
                    if neighbor not in visited:
                        visited[neighbor] = depth + 1
                        next_frontier.append(neighbor)
                    seen_edges.add(identity)
                    traversed_edges.append(
                        {**edge, "depth": depth + 1, "from_node_cid": node_cid}
                    )
                    node_types.setdefault(
                        neighbor, str(edge.get("neighbor_node_type") or "")
                    )
                    if len(traversed_edges) >= max_edges:
                        stop_reason = "max_edges"
                        break
                if stop_reason in {"max_edges", "max_nodes", "max_shards"}:
                    break
            if stop_reason in {"max_edges", "max_nodes", "max_shards"}:
                break
            frontier = next_frontier
            if not frontier:
                stop_reason = "frontier_exhausted"
                break
            if depth + 1 == max_depth:
                stop_reason = "max_depth"
        hydrated = self._graph_nodes(list(visited)) if hydrate else {}
        nodes = []
        for node_cid, depth in sorted(
            visited.items(), key=lambda item: (item[1], item[0])
        ):
            node = {
                "depth": depth,
                "node_cid": node_cid,
                "node_type": node_types.get(node_cid, ""),
            }
            if node_cid in hydrated:
                node.update(hydrated[node_cid])
                node["depth"] = depth
            nodes.append(node)
        return {
            "dataset_repo_id": self.resolver.repo_id,
            "hub_revision": self.resolver.revision,
            "diagnostics": {
                "adjacency_shards_fetched": len(used_paths),
                "complete": stop_reason == "frontier_exhausted",
                "direction": direction,
                "edge_types": sorted(wanted),
                "max_depth": max_depth,
                "max_edges": max_edges,
                "max_nodes": max_nodes,
                "max_shards": max_shards,
                "per_node_limit": per_node_limit,
                "stop_reason": stop_reason,
            },
            "edges": traversed_edges,
            "fetch_trace": self.resolver.trace(),
            "mode": "graph_walk",
            "nodes": nodes,
            "start_node_cid": start_node_cid,
        }


def _graph_directions(value: str) -> tuple[str, ...]:
    direction = str(value or "").strip().lower()
    if direction == "both":
        return ("outgoing", "incoming")
    if direction in {"incoming", "outgoing"}:
        return (direction,)
    raise RemoteQueryError(
        "graph direction must be incoming, outgoing, or both"
    )


def _graph_edge_order_key(edge: Mapping[str, Any]) -> tuple[Any, ...]:
    score = edge.get("score")
    return (
        1 if score is None else 0,
        -(float(score) if score is not None else 0.0),
        str(edge.get("edge_type") or ""),
        str(edge.get("neighbor_cid") or ""),
        str(edge.get("edge_cid") or ""),
        str(edge.get("direction") or ""),
    )


def _validate_graph_bounds(*, limit: int, offset: int, max_shards: int) -> None:
    if not 1 <= int(limit) <= MAX_GRAPH_EDGES:
        raise RemoteQueryError(
            f"graph limit must be between 1 and {MAX_GRAPH_EDGES}"
        )
    if not 0 <= int(offset) <= MAX_GRAPH_EDGES:
        raise RemoteQueryError(
            f"graph offset must be between 0 and {MAX_GRAPH_EDGES}"
        )
    if not 1 <= int(max_shards) <= MAX_GRAPH_SHARDS:
        raise RemoteQueryError(
            f"max_shards must be between 1 and {MAX_GRAPH_SHARDS}"
        )


def _validate_graph_key(value: str, *, name: str) -> None:
    key = str(value or "").strip()
    if (
        key != value
        or not 3 <= len(key) <= 256
        or any(character.isspace() for character in key)
        or "/" in key
        or "\\" in key
    ):
        raise RemoteQueryError(f"{name} is malformed")


def _read_query_vector(value: str) -> list[float]:
    raw = value
    try:
        # Inline vectors are commonly several kilobytes long.  Treat an array
        # literal as JSON before constructing or statting a filesystem path;
        # otherwise Path.is_file() can fail with ENAMETOOLONG.
        if not value.lstrip().startswith("["):
            candidate = Path(value).expanduser()
            if candidate.is_file():
                raw = candidate.read_text(encoding="utf-8")
        parsed = json.loads(raw)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RemoteQueryError("query vector JSON is malformed") from exc
    if (
        not isinstance(parsed, list)
        or not parsed
        or len(parsed) > MAX_QUERY_VECTOR_DIMENSION
    ):
        raise RemoteQueryError("query vector JSON must be a bounded array")
    try:
        result = [float(item) for item in parsed]
    except (TypeError, ValueError, OverflowError):
        raise RemoteQueryError("query vector JSON contains invalid values") from None
    if any(not math.isfinite(item) for item in result):
        raise RemoteQueryError("query vector JSON contains non-finite values")
    return result


def _bound_model_name(manifest: Mapping[str, Any], asserted: str | None) -> str:
    vector = manifest.get("vector")
    if not isinstance(vector, Mapping):
        raise RemoteQueryError("release vector configuration is missing")
    model_name = vector.get("model_name")
    if (
        not isinstance(model_name, str)
        or not model_name
        or any(character.isspace() for character in model_name)
    ):
        raise RemoteQueryError("release embedding model binding is malformed")
    if asserted is not None and asserted != model_name:
        raise RemoteQueryError(
            "--model must exactly match the release embedding model binding"
        )
    return model_name


def _embedding_model_binding(
    manifest: Mapping[str, Any],
    asserted: str | None,
) -> tuple[str, str, str]:
    """Resolve a Hub model ID and immutable revision from the release."""

    model_name = _bound_model_name(manifest, asserted)
    vector = dict(manifest["vector"])
    model_id = vector.get("model_id")
    model_revision = vector.get("model_revision")
    if not isinstance(model_id, str) or not model_id:
        if "@" in model_name:
            model_id, _, embedded_revision = model_name.rpartition("@")
            if model_revision is None:
                model_revision = embedded_revision
    if (
        not isinstance(model_id, str)
        or not model_id
        or any(character.isspace() for character in model_id)
        or not isinstance(model_revision, str)
        or _MODEL_REVISION_RE.fullmatch(model_revision) is None
        or model_name != f"{model_id}@{model_revision}"
    ):
        raise RemoteQueryError(
            "release embedding model must bind a Hub model ID to a "
            "40-character immutable revision"
        )
    return model_name, model_id, model_revision


def _embed_query(
    query: str,
    *,
    model_id: str,
    model_revision: str,
    device: str,
) -> list[float]:
    if not str(query).strip():
        raise RemoteQueryError("query text is required for local embedding")
    try:
        import torch
        from sentence_transformers import SentenceTransformer
    except ImportError as exc:
        raise RemoteQueryError(
            "sentence-transformers and torch are required to embed a query"
        ) from exc
    if device == "cuda" and not torch.cuda.is_available():
        raise RemoteQueryError("CUDA was requested but is not available")
    model = None
    try:
        model = SentenceTransformer(
            model_id,
            device=device,
            revision=model_revision,
            trust_remote_code=False,
        )
        vector = model.encode(
            [query],
            batch_size=1,
            convert_to_numpy=True,
            normalize_embeddings=True,
            show_progress_bar=False,
        )[0]
        return [float(value) for value in vector]
    except RemoteQueryError:
        raise
    except Exception as exc:
        # Do not echo model-library exception text: it can contain paths,
        # request URLs, or authentication context.
        raise RemoteQueryError(
            f"query embedding failed ({type(exc).__name__})"
        ) from None
    finally:
        del model
        gc.collect()
        if device == "cuda":
            try:
                torch.cuda.empty_cache()
            except Exception:
                pass


# ---------------------------------------------------------------------------
# High-level read-only corpus adapter (discovery, validation, traversals)
# ---------------------------------------------------------------------------

# Alias for callers that prefer adapter-domain naming.
CVEfixesAdapterError = RemoteQueryError

# Environment gates for full-corpus integration receipts.
ENV_RELEASE_ROOT = "CVEFIXES_CORPUS_ROOT"
ENV_RELEASE_ROOT_ALT = "IPFS_DATASETS_CVEFIXES_RELEASE_ROOT"
ENV_SOURCE_ROOT = "CVEFIXES_SOURCE_ROOT"
ENV_BUILD_ROOT = "CVEFIXES_BUILD_ROOT"

DEFAULT_BUILD_ROOT = Path("/home/barberb/lift_coding/.cvefixes-build")
DEFAULT_RELEASE_CANDIDATES = (
    "release-with-original-v2",
    "release-with-original",
    "release",
)
LOCAL_FIXTURE_REVISION = "0" * 40

# Expected full-corpus pins from the KGP-002 inventory / release README.
EXPECTED_PROVENANCE = {
    "source_dataset_id": "hitoshura25/cvefixes",
    "source_revision": "d4f5c4ea65329d9ccbb8a3b3149e5d06eda5edb2",
    "graph_root_cid": "bafkreielsquxgqxh6qzb3444bqjlicl34fxqtkyjebwa5h3vqhtaygynee",
    "derived_dataset_id": "Publicus/cvefixes-security-ir-graphrag",
    "license_expression": "Apache-2.0",
}
EXPECTED_FULL_COUNTS = {
    "graph_nodes": 85169,
    "graph_edges": 167364,
    "original_data_rows": 12987,
    "corpus_rows": 123585,
    "vector_rows": 123585,
}

# Node kinds used by representative security-graph traversals.
# "file" is represented as code_unit (path-bearing code change unit).
TRAVERSAL_NODE_TYPES = frozenset(
    {"cve", "cwe", "commit", "code_unit", "repository", "source", "language"}
)
FILE_NODE_TYPES = frozenset({"code_unit"})

LEGACY_QUERY_SCRIPT_CANDIDATES = (
    Path(
        "/home/barberb/lift_coding/hallucinate_app/ipfs_accelerate_py/"
        "ipfs_datasets_py/scripts/ops/security_ir/query_cvefixes_security_ir.py"
    ),
    Path(
        "/home/barberb/lift_coding/data/logic_software_verification_program/"
        "repo/ipfs_datasets_py/scripts/ops/security_ir/query_cvefixes_security_ir.py"
    ),
)

_ARTIFACT_KIND_PREFIXES = {
    "graph_nodes": "data/graph/nodes/",
    "graph_edges": "data/graph/edges/",
    "graph_outgoing_adjacency": "data/graph/adjacency/outgoing/",
    "graph_incoming_adjacency": "data/graph/adjacency/incoming/",
    "vectors": "data/vectors/",
    "corpus": "data/corpus/",
    "bm25_postings": "data/bm25/postings/",
    "original_data": "data/original/",
}


def _env_path(name: str) -> Path | None:
    raw = os.environ.get(name)
    if not raw:
        return None
    return Path(raw).expanduser()


def discover_build_root() -> Path | None:
    """Locate the CVEfixes build tree, or return None when unavailable."""

    for name in (ENV_BUILD_ROOT,):
        candidate = _env_path(name)
        if candidate is not None and candidate.is_dir():
            return candidate.resolve()
    if DEFAULT_BUILD_ROOT.is_dir():
        return DEFAULT_BUILD_ROOT.resolve()
    return None


def discover_release_root() -> Path | None:
    """Locate a generated CVEfixes release root (env-gated or default)."""

    for name in (ENV_RELEASE_ROOT, ENV_RELEASE_ROOT_ALT):
        candidate = _env_path(name)
        if candidate is not None and candidate.is_dir():
            manifest = candidate / DEFAULT_MANIFEST
            if manifest.is_file():
                return candidate.resolve()
    build = discover_build_root()
    if build is None:
        return None
    for name in DEFAULT_RELEASE_CANDIDATES:
        candidate = build / name
        if (candidate / DEFAULT_MANIFEST).is_file():
            return candidate.resolve()
    return None


def discover_source_root() -> Path | None:
    """Locate the pinned source Parquet tree (upstream CVEfixes snapshot)."""

    candidate = _env_path(ENV_SOURCE_ROOT)
    if candidate is not None and candidate.is_dir():
        return candidate.resolve()
    build = discover_build_root()
    if build is None:
        return None
    source = build / "source" / "data"
    if source.is_dir() and any(source.glob("*.parquet")):
        return source.resolve()
    # Packaged original bodies live under the release tree.
    release = discover_release_root()
    if release is not None:
        original = release / "data" / "original"
        if original.is_dir() and any(original.glob("*.parquet")):
            return original.resolve()
    return None


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(8 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _list_parquet_files(directory: Path) -> list[Path]:
    if not directory.is_dir():
        return []
    return sorted(
        path
        for path in directory.rglob("*.parquet")
        if path.is_file() and not path.is_symlink()
    )


def validate_source_parquet(
    source_root: Path,
    *,
    expected_rows: int | None = None,
) -> dict[str, Any]:
    """Discover and validate source Parquet shards (row counts + readability)."""

    root = Path(source_root).expanduser().resolve()
    if not root.is_dir():
        raise CVEfixesAdapterError(f"source root is missing: {root}")
    shards = _list_parquet_files(root)
    if not shards:
        raise CVEfixesAdapterError(f"no source Parquet shards under {root}")
    try:
        import pyarrow.parquet as pq
    except ImportError as exc:
        raise CVEfixesAdapterError("pyarrow is required for source validation") from exc

    total_rows = 0
    shard_receipts: list[dict[str, Any]] = []
    for shard in shards:
        try:
            meta = pq.read_metadata(shard)
            rows = int(meta.num_rows)
            schema = pq.read_schema(shard)
        except Exception as exc:
            raise CVEfixesAdapterError(
                f"corrupt or unreadable source shard: {shard.name}"
            ) from exc
        if rows <= 0:
            raise CVEfixesAdapterError(f"empty source shard: {shard.name}")
        total_rows += rows
        shard_receipts.append(
            {
                "path": str(shard.relative_to(root)),
                "row_count": rows,
                "num_columns": len(schema.names),
                "columns": list(schema.names),
                "size_bytes": shard.stat().st_size,
                "sha256": _sha256_file(shard),
            }
        )
    if expected_rows is not None and total_rows != int(expected_rows):
        raise CVEfixesAdapterError(
            f"source row count differs: expected {expected_rows}, got {total_rows}"
        )
    return {
        "source_root": str(root),
        "shard_count": len(shards),
        "row_count": total_rows,
        "shards": shard_receipts,
    }


def _manifest_artifact_map(manifest: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, Sequence) or isinstance(artifacts, (str, bytes)):
        return {}
    mapping: dict[str, Mapping[str, Any]] = {}
    for item in artifacts:
        if not isinstance(item, Mapping):
            continue
        path = item.get("path") or item.get("relative_path")
        if isinstance(path, str) and path:
            mapping[path] = item
    return mapping


def _verify_path_checksum(
    root: Path,
    relative_path: str,
    *,
    sha256: str | None = None,
    size_bytes: int | None = None,
    cid: str | None = None,
) -> dict[str, Any]:
    path = root.joinpath(*_safe_relative_path(relative_path).parts)
    if path.is_symlink() or not path.is_file():
        raise CVEfixesAdapterError(f"release file is missing: {relative_path}")
    actual_size = path.stat().st_size
    if size_bytes is not None and actual_size != int(size_bytes):
        raise CVEfixesAdapterError(f"artifact size differs: {relative_path}")
    digest_hex = _sha256_file(path)
    if sha256 is not None and digest_hex != sha256:
        raise CVEfixesAdapterError(f"artifact digest differs: {relative_path}")
    if cid is not None:
        computed_cid = _raw_sha256_cid(bytes.fromhex(digest_hex))
        if computed_cid != cid:
            raise CVEfixesAdapterError(f"artifact CID differs: {relative_path}")
    return {
        "relative_path": relative_path,
        "size_bytes": actual_size,
        "sha256": digest_hex,
        "cid": cid,
    }


def validate_manifest(
    release_root: Path,
    *,
    require_counts: bool = False,
) -> dict[str, Any]:
    """Load and structurally validate a generated release manifest."""

    root = Path(release_root).expanduser().resolve()
    manifest_path = root / DEFAULT_MANIFEST
    if not manifest_path.is_file():
        raise CVEfixesAdapterError(f"manifest is missing: {manifest_path}")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CVEfixesAdapterError("manifest.json is malformed") from exc
    if not isinstance(manifest, dict):
        raise CVEfixesAdapterError("manifest.json must be an object")
    schema = manifest.get("schema_version")
    if schema not in SUPPORTED_RELEASE_SCHEMAS:
        raise CVEfixesAdapterError("unsupported CVEfixes release manifest")
    primary_key = manifest.get("primary_key")
    if primary_key not in {None, "entry_cid"}:
        raise CVEfixesAdapterError("CVEfixes release primary key must be entry_cid")
    indexes = manifest.get("indexes")
    if not isinstance(indexes, Mapping) or not indexes:
        raise CVEfixesAdapterError("release index descriptors are missing")
    for name, expected_path in _INDEX_PATHS.items():
        if name not in indexes:
            # graph edge index is optional in the query client set; other
            # indexes used by the query client are required.
            if name in {
                "bm25_keyword_shards",
                "corpus_chunks",
                "graph_node_chunks",
                "graph_outgoing_adjacency",
                "graph_incoming_adjacency",
                "vector_chunks",
            }:
                raise CVEfixesAdapterError(f"release index is missing: {name}")
            continue
        descriptor = indexes[name]
        if not isinstance(descriptor, Mapping):
            raise CVEfixesAdapterError(f"release index is malformed: {name}")
        relative = str(descriptor.get("relative_path") or "")
        if relative != expected_path:
            raise CVEfixesAdapterError(f"release index path differs: {name}")
        _validate_descriptor_shape(descriptor)
        _verify_path_checksum(
            root,
            relative,
            sha256=str(descriptor["sha256"]),
            size_bytes=int(descriptor["size_bytes"]),
            cid=str(descriptor["cid"]),
        )
    counts = manifest.get("counts") if isinstance(manifest.get("counts"), Mapping) else {}
    if require_counts and not counts:
        raise CVEfixesAdapterError("release counts are missing")
    source = manifest.get("source") if isinstance(manifest.get("source"), Mapping) else {}
    graph = manifest.get("graph") if isinstance(manifest.get("graph"), Mapping) else {}
    return {
        "manifest_path": str(manifest_path),
        "manifest_sha256": _sha256_file(manifest_path),
        "schema_version": schema,
        "dataset_id": manifest.get("dataset_id"),
        "release_root_cid": manifest.get("release_root"),
        "derived_dataset_root": manifest.get("derived_dataset_root"),
        "primary_key": primary_key or "entry_cid",
        "counts": dict(counts),
        "source": dict(source),
        "graph": dict(graph),
        "index_names": sorted(str(key) for key in indexes),
        "manifest": manifest,
    }


def validate_graph_and_vector_shards(
    release_root: Path,
    manifest: Mapping[str, Any],
    *,
    verify_data_checksums: bool = True,
    max_data_shards: int | None = None,
) -> dict[str, Any]:
    """Validate node/edge/adjacency/vector shard presence and integrity."""

    root = Path(release_root).expanduser().resolve()
    try:
        import pyarrow.parquet as pq
    except ImportError as exc:
        raise CVEfixesAdapterError("pyarrow is required for shard validation") from exc

    artifact_map = _manifest_artifact_map(manifest)
    kind_receipts: dict[str, dict[str, Any]] = {}
    verified = 0
    for kind, prefix in _ARTIFACT_KIND_PREFIXES.items():
        directory = root.joinpath(*PurePosixPath(prefix.rstrip("/")).parts)
        shards = _list_parquet_files(directory)
        total_rows = 0
        shard_rows: list[dict[str, Any]] = []
        for index, shard in enumerate(shards):
            if max_data_shards is not None and index >= max_data_shards:
                break
            relative = shard.relative_to(root).as_posix()
            try:
                meta = pq.read_metadata(shard)
                rows = int(meta.num_rows)
            except Exception as exc:
                raise CVEfixesAdapterError(
                    f"corrupt or unreadable shard: {relative}"
                ) from exc
            if rows <= 0:
                raise CVEfixesAdapterError(f"empty data shard: {relative}")
            total_rows += rows
            receipt: dict[str, Any] = {
                "relative_path": relative,
                "row_count": rows,
                "size_bytes": shard.stat().st_size,
            }
            if verify_data_checksums:
                digest = _sha256_file(shard)
                receipt["sha256"] = digest
                descriptor = artifact_map.get(relative)
                if descriptor is not None:
                    expected_sha = descriptor.get("sha256")
                    expected_size = descriptor.get("byte_length") or descriptor.get(
                        "size_bytes"
                    )
                    expected_cid = descriptor.get("content_id") or descriptor.get("cid")
                    if expected_sha and digest != expected_sha:
                        raise CVEfixesAdapterError(
                            f"artifact digest differs: {relative}"
                        )
                    if expected_size is not None and shard.stat().st_size != int(
                        expected_size
                    ):
                        raise CVEfixesAdapterError(
                            f"artifact size differs: {relative}"
                        )
                    if expected_cid:
                        if _raw_sha256_cid(bytes.fromhex(digest)) != expected_cid:
                            raise CVEfixesAdapterError(
                                f"artifact CID differs: {relative}"
                            )
                        receipt["cid"] = expected_cid
                verified += 1
            shard_rows.append(receipt)
        kind_receipts[kind] = {
            "directory": prefix,
            "shard_count": len(shards),
            "checked_shards": len(shard_rows),
            "row_count_checked": total_rows,
            "shards": shard_rows,
        }
        # Full inventory: empty graph/vector kinds are fatal for a complete release.
        if kind in {
            "graph_nodes",
            "graph_edges",
            "graph_outgoing_adjacency",
            "graph_incoming_adjacency",
            "vectors",
        } and not shards:
            raise CVEfixesAdapterError(f"missing {kind} shards under {prefix}")

    counts = manifest.get("counts") if isinstance(manifest.get("counts"), Mapping) else {}
    comparisons: dict[str, Any] = {}
    if counts:
        node_shards = kind_receipts.get("graph_nodes", {})
        edge_shards = kind_receipts.get("graph_edges", {})
        # Only compare when every shard was enumerated (no max_data_shards cap).
        if max_data_shards is None:
            if "graph_nodes" in counts and node_shards.get("row_count_checked") != int(
                counts["graph_nodes"]
            ):
                raise CVEfixesAdapterError(
                    "graph node count differs from manifest.counts"
                )
            if "graph_edges" in counts and edge_shards.get("row_count_checked") != int(
                counts["graph_edges"]
            ):
                raise CVEfixesAdapterError(
                    "graph edge count differs from manifest.counts"
                )
            comparisons["graph_nodes"] = node_shards.get("row_count_checked")
            comparisons["graph_edges"] = edge_shards.get("row_count_checked")
    return {
        "kinds": kind_receipts,
        "checksums_verified": verified,
        "count_comparisons": comparisons,
    }


def open_release_reader(
    release_root: Path | str,
    *,
    revision: str = LOCAL_FIXTURE_REVISION,
    repo_id: str = DEFAULT_REPO_ID,
    cache_dir: Path | None = None,
) -> CVEfixesRemoteIndex:
    """Open a local release through the integrity-checked query reader."""

    root = Path(release_root).expanduser().resolve()
    if not (root / DEFAULT_MANIFEST).is_file():
        raise CVEfixesAdapterError(f"manifest is missing under {root}")
    resolver = ArtifactResolver(
        repo_id=repo_id,
        revision=revision,
        cache_dir=cache_dir or (root / ".cache"),
        local_root=root,
    )
    return CVEfixesRemoteIndex(resolver)


def find_nodes_by_type(
    reader: CVEfixesRemoteIndex,
    node_type: str,
    *,
    limit: int = 25,
    label_prefix: str | None = None,
) -> list[dict[str, Any]]:
    """Scan graph node shards for a node_type (bounded)."""

    if not node_type or not isinstance(node_type, str):
        raise CVEfixesAdapterError("node_type must be a non-empty string")
    if not 1 <= int(limit) <= MAX_GRAPH_NODES:
        raise CVEfixesAdapterError(f"limit must be between 1 and {MAX_GRAPH_NODES}")
    meta = reader._meta_rows("graph_node_chunks")
    matches: list[dict[str, Any]] = []
    for descriptor in meta:
        table = reader._read_shard("graph_node_chunks", descriptor)
        _require_columns(
            table,
            ["node_cid", "node_type", "label", "entry_cid", "properties_json"],
            label=str(descriptor.get("relative_path")),
        )
        for row in table.to_pylist():
            if str(row.get("node_type") or "") != node_type:
                continue
            label = str(row.get("label") or "")
            if label_prefix is not None and not label.startswith(label_prefix):
                continue
            matches.append(
                {str(key): _json_value(value) for key, value in row.items()}
            )
            if len(matches) >= limit:
                return matches
    return matches


def traverse_cve_neighborhood(
    reader: CVEfixesRemoteIndex,
    cve_id: str,
    *,
    max_depth: int = 2,
    max_nodes: int = 64,
    max_edges: int = 256,
    max_shards: int = 32,
    per_node_limit: int = 32,
) -> dict[str, Any]:
    """Representative CVE → CWE / commit / code-unit (file) traversal."""

    if not isinstance(cve_id, str) or not cve_id.startswith("CVE-"):
        raise CVEfixesAdapterError("cve_id must look like CVE-YYYY-…")
    nodes = find_nodes_by_type(
        reader, "cve", limit=1, label_prefix=cve_id
    )
    # Exact label match preferred.
    exact = [node for node in nodes if str(node.get("label")) == cve_id]
    if not exact:
        # Broader scan if prefix search hit something else or missed.
        nodes = find_nodes_by_type(reader, "cve", limit=5000)
        exact = [node for node in nodes if str(node.get("label")) == cve_id]
    if not exact:
        return {
            "found": False,
            "cve_id": cve_id,
            "nodes": [],
            "edges": [],
            "by_type": {},
        }
    seed = exact[0]
    seed_cid = str(seed["node_cid"])
    walk = reader.graph_walk(
        seed_cid,
        direction="outgoing",
        max_depth=max_depth,
        max_nodes=max_nodes,
        max_edges=max_edges,
        per_node_limit=per_node_limit,
        max_shards=max_shards,
        hydrate=True,
    )
    by_type: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for node in walk.get("nodes") or []:
        by_type[str(node.get("node_type") or "")].append(node)
    return {
        "found": True,
        "cve_id": cve_id,
        "seed": seed,
        "walk": walk,
        "nodes": walk.get("nodes") or [],
        "edges": walk.get("edges") or [],
        "by_type": {
            key: values for key, values in sorted(by_type.items())
        },
        "has_cwe": bool(by_type.get("cwe")),
        "has_commit": bool(by_type.get("commit")),
        "has_file": bool(
            by_type.get("code_unit") or by_type.get("file")
        ),
        "has_repository": bool(by_type.get("repository")),
    }


def load_legacy_query_module() -> Any | None:
    """Import the nested-tree query script for differential parity, if present."""

    for path in LEGACY_QUERY_SCRIPT_CANDIDATES:
        if not path.is_file():
            continue
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "kgp024_legacy_query_cvefixes_security_ir", path
        )
        if spec is None or spec.loader is None:
            continue
        module = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(module)
        except Exception:
            continue
        return module
    return None


def differential_query_parity(
    release_root: Path,
    *,
    revision: str = LOCAL_FIXTURE_REVISION,
    bm25_query: str = "overflow",
    graph_node_cid: str | None = None,
) -> dict[str, Any]:
    """Compare this adapter against the existing query script when available."""

    root = Path(release_root).expanduser().resolve()
    adapter_reader = open_release_reader(root, revision=revision)
    legacy = load_legacy_query_module()
    if legacy is None:
        # Self-consistency receipt when the nested script is not on this host.
        bm25 = adapter_reader.bm25(bm25_query, top_k=3)
        return {
            "legacy_available": False,
            "parity": "self_only",
            "adapter_bm25_count": bm25["result_count"],
            "adapter_mode": bm25["mode"],
        }

    legacy_resolver = legacy.ArtifactResolver(
        repo_id=DEFAULT_REPO_ID,
        revision=revision,
        cache_dir=root / ".cache-legacy",
        local_root=root,
    )
    legacy_index = legacy.CVEfixesRemoteIndex(legacy_resolver)

    adapter_bm25 = adapter_reader.bm25(bm25_query, top_k=5, include_content=True)
    legacy_bm25 = legacy_index.bm25(bm25_query, top_k=5, include_content=True)
    if adapter_bm25["result_count"] != legacy_bm25["result_count"]:
        raise CVEfixesAdapterError("BM25 result_count parity failure")
    adapter_ids = [row.get("entry_cid") for row in adapter_bm25["results"]]
    legacy_ids = [row.get("entry_cid") for row in legacy_bm25["results"]]
    if adapter_ids != legacy_ids:
        raise CVEfixesAdapterError("BM25 ranking parity failure")
    for left, right in zip(adapter_bm25["results"], legacy_bm25["results"]):
        if abs(float(left["score"]) - float(right["score"])) > 1e-9:
            raise CVEfixesAdapterError("BM25 score parity failure")
        if left.get("matched_terms") != right.get("matched_terms"):
            raise CVEfixesAdapterError("BM25 matched_terms parity failure")

    graph_parity: dict[str, Any] = {"skipped": True}
    if graph_node_cid:
        a_neighbors = adapter_reader.graph_neighbors(
            graph_node_cid, direction="outgoing", limit=10, max_shards=8
        )
        l_neighbors = legacy_index.graph_neighbors(
            graph_node_cid, direction="outgoing", limit=10, max_shards=8
        )
        if a_neighbors["results"] != l_neighbors["results"]:
            raise CVEfixesAdapterError("graph_neighbors parity failure")
        graph_parity = {
            "skipped": False,
            "neighbor_count": len(a_neighbors["results"]),
            "node_cid": graph_node_cid,
        }
    return {
        "legacy_available": True,
        "parity": "matched",
        "bm25_result_count": adapter_bm25["result_count"],
        "bm25_entry_cids": adapter_ids,
        "graph": graph_parity,
        "legacy_path": str(
            next(p for p in LEGACY_QUERY_SCRIPT_CANDIDATES if p.is_file())
        ),
    }


class CVEfixesCorpusAdapter:
    """Read-only facade over a CVEfixes release (+ optional source Parquet)."""

    def __init__(
        self,
        release_root: Path | str,
        *,
        source_root: Path | str | None = None,
        revision: str = LOCAL_FIXTURE_REVISION,
        repo_id: str = DEFAULT_REPO_ID,
    ) -> None:
        self.release_root = Path(release_root).expanduser().resolve()
        self.source_root = (
            Path(source_root).expanduser().resolve()
            if source_root is not None
            else None
        )
        self.revision = revision
        self.repo_id = repo_id
        self._reader: CVEfixesRemoteIndex | None = None
        self._manifest_receipt: dict[str, Any] | None = None

    @classmethod
    def discover(
        cls,
        *,
        require_release: bool = True,
    ) -> "CVEfixesCorpusAdapter":
        release = discover_release_root()
        if release is None and require_release:
            raise CVEfixesAdapterError(
                "no CVEfixes release root discovered; set "
                f"{ENV_RELEASE_ROOT} or install the local build tree"
            )
        if release is None:
            raise CVEfixesAdapterError("no CVEfixes release root discovered")
        return cls(release, source_root=discover_source_root())

    @property
    def reader(self) -> CVEfixesRemoteIndex:
        if self._reader is None:
            self._reader = open_release_reader(
                self.release_root,
                revision=self.revision,
                repo_id=self.repo_id,
            )
        return self._reader

    def validate(
        self,
        *,
        verify_data_checksums: bool = True,
        max_data_shards: int | None = None,
        expected_full_corpus: bool = False,
    ) -> dict[str, Any]:
        """Validate manifest, indexes, shards, optional source, and provenance."""

        manifest_receipt = validate_manifest(
            self.release_root,
            require_counts=expected_full_corpus,
        )
        self._manifest_receipt = manifest_receipt
        manifest = manifest_receipt["manifest"]
        shard_receipt = validate_graph_and_vector_shards(
            self.release_root,
            manifest,
            verify_data_checksums=verify_data_checksums,
            max_data_shards=max_data_shards,
        )
        source_receipt: dict[str, Any] | None = None
        if self.source_root is not None:
            expected_rows = None
            counts = manifest_receipt.get("counts") or {}
            if expected_full_corpus:
                expected_rows = int(
                    counts.get(
                        "original_data_rows",
                        EXPECTED_FULL_COUNTS["original_data_rows"],
                    )
                )
            source_receipt = validate_source_parquet(
                self.source_root, expected_rows=expected_rows
            )

        provenance = {
            "source_dataset_id": (manifest_receipt.get("source") or {}).get(
                "dataset_id"
            ),
            "source_revision": (manifest_receipt.get("source") or {}).get(
                "source_revision"
            ),
            "license_expression": (manifest_receipt.get("source") or {}).get(
                "license_expression"
            ),
            "graph_root_cid": (manifest_receipt.get("graph") or {}).get(
                "graph_root"
            ),
            "derived_dataset_id": manifest_receipt.get("dataset_id"),
            "release_root_cid": manifest_receipt.get("release_root_cid"),
            "derived_dataset_root": manifest_receipt.get("derived_dataset_root"),
        }
        if expected_full_corpus:
            for key, expected in EXPECTED_PROVENANCE.items():
                actual = provenance.get(key)
                if actual != expected:
                    raise CVEfixesAdapterError(
                        f"provenance mismatch for {key}: "
                        f"expected {expected!r}, got {actual!r}"
                    )
            counts = manifest_receipt.get("counts") or {}
            for key, expected in EXPECTED_FULL_COUNTS.items():
                if key in counts and int(counts[key]) != int(expected):
                    raise CVEfixesAdapterError(
                        f"full-corpus count mismatch for {key}"
                    )

        # Ensure the query reader can open and load a meta index.
        _ = self.reader._meta_rows("graph_node_chunks")

        return {
            "schema": "cvefixes-corpus-validation-receipt/v1",
            "release_root": str(self.release_root),
            "source_root": (
                str(self.source_root) if self.source_root is not None else None
            ),
            "revision": self.revision,
            "manifest": {
                key: value
                for key, value in manifest_receipt.items()
                if key != "manifest"
            },
            "shards": shard_receipt,
            "source": source_receipt,
            "provenance": provenance,
            "expected_full_corpus": expected_full_corpus,
        }

    def bm25(self, query: str, **kwargs: Any) -> dict[str, Any]:
        return self.reader.bm25(query, **kwargs)

    def vector(self, query: str, **kwargs: Any) -> dict[str, Any]:
        return self.reader.vector(query, **kwargs)

    def graph_node(self, node_cid: str) -> dict[str, Any]:
        return self.reader.graph_node(node_cid)

    def graph_neighbors(self, node_cid: str, **kwargs: Any) -> dict[str, Any]:
        return self.reader.graph_neighbors(node_cid, **kwargs)

    def graph_walk(self, start_node_cid: str, **kwargs: Any) -> dict[str, Any]:
        return self.reader.graph_walk(start_node_cid, **kwargs)

    def traverse_cve(self, cve_id: str, **kwargs: Any) -> dict[str, Any]:
        return traverse_cve_neighborhood(self.reader, cve_id, **kwargs)

    def differential_parity(self, **kwargs: Any) -> dict[str, Any]:
        return differential_query_parity(
            self.release_root, revision=self.revision, **kwargs
        )


def build_tiny_fixture_release(root: Path) -> Path:
    """Materialize a tiny, integrity-checked CVEfixes-shaped release fixture.

    The layout mirrors the production query client tests so differential
    comparisons and missing/corrupt shard tests stay realistic.
    """

    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ImportError as exc:
        raise CVEfixesAdapterError(
            "pyarrow is required to build the tiny fixture"
        ) from exc

    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)

    def write_parquet(path: Path, rows: list[dict[str, Any]]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        pq.write_table(pa.Table.from_pylist(rows), path, compression="zstd")

    def descriptor(path: Path, *, row_count: int) -> dict[str, Any]:
        content = path.read_bytes()
        digest = hashlib.sha256(content).digest()
        return {
            "cid": _raw_sha256_cid(digest),
            "relative_path": path.relative_to(root).as_posix(),
            "row_count": row_count,
            "sha256": digest.hex(),
            "size_bytes": len(content),
        }

    def meta_row(
        path: Path,
        *,
        shard_id: int,
        row_count: int,
        first_key: str,
        last_key: str,
        kind: str,
        start_document_index: int = -1,
        end_document_index: int = -1,
        **extra: Any,
    ) -> dict[str, Any]:
        return {
            **descriptor(path, row_count=row_count),
            "end_document_index": end_document_index,
            "first_key": first_key,
            "kind": kind,
            "last_key": last_key,
            "schema_version": META_SCHEMA_VERSION,
            "shard_id": shard_id,
            "start_document_index": start_document_index,
            **extra,
        }

    def write_index(name: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
        path = root / "indexes" / f"{name}.parquet"
        write_parquet(path, rows)
        return descriptor(path, row_count=len(rows))

    # --- corpus ---
    corpus_path = root / "data/corpus/part-000000.parquet"
    corpus_rows = [
        {
            "authority": "context_only",
            "document_index": 0,
            "entry_cid": "entry-a",
            "kind": "security_ir",
            "node_cid": "node-cve-1",
            "schema_version": "cvefixes-hf-corpus/v1",
            "text": "buffer overflow in parser",
            "title": "CVE-2018-1000524 overflow repair",
        },
        {
            "authority": "context_only",
            "document_index": 1,
            "entry_cid": "entry-b",
            "kind": "security_ir",
            "node_cid": "node-commit-1",
            "schema_version": "cvefixes-hf-corpus/v1",
            "text": "sanitize an untrusted path",
            "title": "CVE path repair",
        },
    ]
    write_parquet(corpus_path, corpus_rows)

    # --- bm25 postings ---
    posting_path = root / "data/bm25/postings/part-000000.parquet"
    posting_rows = [
        {
            "body_frequencies": [1],
            "corpus_frequency": 1,
            "document_frequency": 1,
            "document_indices": [0],
            "document_lengths": [5],
            "idf": 0.7,
            "posting_chunk_count": 1,
            "posting_chunk_index": 0,
            "schema_version": "cvefixes-hf-bm25-posting/v1",
            "term": "overflow",
            "title_frequencies": [1],
        },
        {
            "body_frequencies": [1],
            "corpus_frequency": 1,
            "document_frequency": 1,
            "document_indices": [1],
            "document_lengths": [5],
            "idf": 0.7,
            "posting_chunk_count": 1,
            "posting_chunk_index": 0,
            "schema_version": "cvefixes-hf-bm25-posting/v1",
            "term": "sanitize",
            "title_frequencies": [1],
        },
    ]
    write_parquet(posting_path, posting_rows)

    # --- vectors ---
    model_revision = "b" * 40
    model_config_cid = _raw_sha256_cid(hashlib.sha256(b"model config").digest())
    vector_specs = [
        (
            root / "data/vectors/part-000000.parquet",
            {
                "chunk_id": "vector-000000",
                "cluster_id": 0,
                "document_index": 0,
                "embedding": [1.0, 0.0],
                "entry_cid": "entry-a",
                "has_embedding": True,
                "model_config_cid": model_config_cid,
                "model_id": "test/model",
                "model_revision": model_revision,
                "schema_version": "cvefixes-hf-vector/v1",
            },
        ),
        (
            root / "data/vectors/part-000001.parquet",
            {
                "chunk_id": "vector-000001",
                "cluster_id": 1,
                "document_index": 1,
                "embedding": [0.0, 1.0],
                "entry_cid": "entry-b",
                "has_embedding": True,
                "model_config_cid": model_config_cid,
                "model_id": "test/model",
                "model_revision": model_revision,
                "schema_version": "cvefixes-hf-vector/v1",
            },
        ),
    ]
    for path, row in vector_specs:
        write_parquet(path, [row])

    # --- graph nodes: CVE, CWE, commit, code_unit (file) ---
    node_path = root / "data/graph/nodes/part-000000.parquet"
    node_rows = [
        {
            "entry_cid": "entry-a",
            "label": "CVE-2018-1000524",
            "node_cid": "node-cve-1",
            "node_type": "cve",
            "properties_json": '{"payload":{"cve_id":"CVE-2018-1000524"}}',
            "schema_version": "cvefixes-hf-graph-node/v1",
        },
        {
            "entry_cid": "entry-cwe",
            "label": "CWE-119",
            "node_cid": "node-cwe-1",
            "node_type": "cwe",
            "properties_json": '{"payload":{"cwe_id":"CWE-119"}}',
            "schema_version": "cvefixes-hf-graph-node/v1",
        },
        {
            "entry_cid": "entry-b",
            "label": "d6a86b5e69e46cc283b1e06c92343319beb42e21",
            "node_cid": "node-commit-1",
            "node_type": "commit",
            "properties_json": (
                '{"payload":{"commit_hash":'
                '"d6a86b5e69e46cc283b1e06c92343319beb42e21"}}'
            ),
            "schema_version": "cvefixes-hf-graph-node/v1",
        },
        {
            "entry_cid": "entry-file",
            "label": "src/parser.c",
            "node_cid": "node-file-1",
            "node_type": "code_unit",
            "properties_json": '{"payload":{"path":"src/parser.c"}}',
            "schema_version": "cvefixes-hf-graph-node/v1",
        },
    ]
    write_parquet(node_path, node_rows)

    # --- edges (for shard presence validation) ---
    edge_path = root / "data/graph/edges/part-000000.parquet"
    edge_rows = [
        {
            "edge_cid": "edge-cve-cwe",
            "edge_type": "CLASSIFIED_AS",
            "properties_json": "{}",
            "query_terms_json": "[]",
            "retrieval_method": "deterministic_graph",
            "schema_version": "cvefixes-hf-graph-edge/v1",
            "score": None,
            "source_cid": "node-cve-1",
            "target_cid": "node-cwe-1",
        },
        {
            "edge_cid": "edge-cve-commit",
            "edge_type": "FIXED_BY",
            "properties_json": "{}",
            "query_terms_json": "[]",
            "retrieval_method": "deterministic_graph",
            "schema_version": "cvefixes-hf-graph-edge/v1",
            "score": None,
            "source_cid": "node-cve-1",
            "target_cid": "node-commit-1",
        },
        {
            "edge_cid": "edge-commit-file",
            "edge_type": "CHANGES",
            "properties_json": "{}",
            "query_terms_json": "[]",
            "retrieval_method": "deterministic_graph",
            "schema_version": "cvefixes-hf-graph-edge/v1",
            "score": None,
            "source_cid": "node-commit-1",
            "target_cid": "node-file-1",
        },
    ]
    write_parquet(edge_path, edge_rows)

    # --- adjacency ---
    out_path = root / "data/graph/adjacency/outgoing/part-000000.parquet"
    out_rows = [
        {
            "direction": "outgoing",
            "edge_cids": ["edge-cve-cwe", "edge-cve-commit"],
            "edge_types": ["CLASSIFIED_AS", "FIXED_BY"],
            "neighbor_cids": ["node-cwe-1", "node-commit-1"],
            "neighbor_count": 2,
            "neighbor_node_types": ["cwe", "commit"],
            "node_cid": "node-cve-1",
            "page_count": 1,
            "page_index": 0,
            "retrieval_methods": ["deterministic_graph"] * 2,
            "schema_version": "cvefixes-hf-graph-adjacency/v1",
            "scores": [1.0, 0.9],
            "total_neighbor_count": 2,
        },
        {
            "direction": "outgoing",
            "edge_cids": ["edge-commit-file"],
            "edge_types": ["CHANGES"],
            "neighbor_cids": ["node-file-1"],
            "neighbor_count": 1,
            "neighbor_node_types": ["code_unit"],
            "node_cid": "node-commit-1",
            "page_count": 1,
            "page_index": 0,
            "retrieval_methods": ["deterministic_graph"],
            "schema_version": "cvefixes-hf-graph-adjacency/v1",
            "scores": [0.8],
            "total_neighbor_count": 1,
        },
        {
            "direction": "outgoing",
            "edge_cids": [],
            "edge_types": [],
            "neighbor_cids": [],
            "neighbor_count": 0,
            "neighbor_node_types": [],
            "node_cid": "node-cwe-1",
            "page_count": 1,
            "page_index": 0,
            "retrieval_methods": [],
            "schema_version": "cvefixes-hf-graph-adjacency/v1",
            "scores": [],
            "total_neighbor_count": 0,
        },
        {
            "direction": "outgoing",
            "edge_cids": [],
            "edge_types": [],
            "neighbor_cids": [],
            "neighbor_count": 0,
            "neighbor_node_types": [],
            "node_cid": "node-file-1",
            "page_count": 1,
            "page_index": 0,
            "retrieval_methods": [],
            "schema_version": "cvefixes-hf-graph-adjacency/v1",
            "scores": [],
            "total_neighbor_count": 0,
        },
    ]
    write_parquet(out_path, out_rows)

    in_path = root / "data/graph/adjacency/incoming/part-000000.parquet"
    in_rows = [
        {
            "direction": "incoming",
            "edge_cids": ["edge-cve-cwe"],
            "edge_types": ["CLASSIFIED_AS"],
            "neighbor_cids": ["node-cve-1"],
            "neighbor_count": 1,
            "neighbor_node_types": ["cve"],
            "node_cid": "node-cwe-1",
            "page_count": 1,
            "page_index": 0,
            "retrieval_methods": ["deterministic_graph"],
            "schema_version": "cvefixes-hf-graph-adjacency/v1",
            "scores": [1.0],
            "total_neighbor_count": 1,
        },
        {
            "direction": "incoming",
            "edge_cids": ["edge-cve-commit"],
            "edge_types": ["FIXED_BY"],
            "neighbor_cids": ["node-cve-1"],
            "neighbor_count": 1,
            "neighbor_node_types": ["cve"],
            "node_cid": "node-commit-1",
            "page_count": 1,
            "page_index": 0,
            "retrieval_methods": ["deterministic_graph"],
            "schema_version": "cvefixes-hf-graph-adjacency/v1",
            "scores": [0.9],
            "total_neighbor_count": 1,
        },
        {
            "direction": "incoming",
            "edge_cids": ["edge-commit-file"],
            "edge_types": ["CHANGES"],
            "neighbor_cids": ["node-commit-1"],
            "neighbor_count": 1,
            "neighbor_node_types": ["commit"],
            "node_cid": "node-file-1",
            "page_count": 1,
            "page_index": 0,
            "retrieval_methods": ["deterministic_graph"],
            "schema_version": "cvefixes-hf-graph-adjacency/v1",
            "scores": [0.8],
            "total_neighbor_count": 1,
        },
        {
            "direction": "incoming",
            "edge_cids": [],
            "edge_types": [],
            "neighbor_cids": [],
            "neighbor_count": 0,
            "neighbor_node_types": [],
            "node_cid": "node-cve-1",
            "page_count": 1,
            "page_index": 0,
            "retrieval_methods": [],
            "schema_version": "cvefixes-hf-graph-adjacency/v1",
            "scores": [],
            "total_neighbor_count": 0,
        },
    ]
    write_parquet(in_path, in_rows)

    # --- original / source parquet ---
    source_dir = root / "source" / "data"
    source_path = source_dir / "train-00000-of-00001.parquet"
    source_rows = [
        {
            "cve_id": "CVE-2018-1000524",
            "cwe_id": "CWE-119",
            "hash": "d6a86b5e69e46cc283b1e06c92343319beb42e21",
            "language": "C",
            "file_paths": ["src/parser.c"],
        }
    ]
    write_parquet(source_path, source_rows)
    original_path = root / "data/original/part-000000.parquet"
    write_parquet(original_path, source_rows)

    index_descriptors = {
        "corpus_chunks": write_index(
            "corpus_chunks",
            [
                meta_row(
                    corpus_path,
                    shard_id=0,
                    row_count=2,
                    first_key="entry-a",
                    last_key="entry-b",
                    kind="corpus",
                    start_document_index=0,
                    end_document_index=1,
                )
            ],
        ),
        "bm25_keyword_shards": write_index(
            "bm25_keyword_shards",
            [
                meta_row(
                    posting_path,
                    shard_id=0,
                    row_count=2,
                    first_key="overflow",
                    last_key="sanitize",
                    kind="bm25_postings",
                )
            ],
        ),
        "vector_chunks": write_index(
            "vector_chunks",
            [
                meta_row(
                    path,
                    shard_id=index,
                    row_count=1,
                    first_key=f"entry-{'a' if index == 0 else 'b'}",
                    last_key=f"entry-{'a' if index == 0 else 'b'}",
                    kind="vectors",
                    start_document_index=index,
                    end_document_index=index,
                    centroid=([1.0, 0.0] if index == 0 else [0.0, 1.0]),
                    centroid_shard_count=1,
                    chunk_in_cluster=0,
                    cluster_id=index,
                    dimension=2,
                    model_name=f"test/model@{model_revision}",
                    shard_centroid=([1.0, 0.0] if index == 0 else [0.0, 1.0]),
                )
                for index, (path, _) in enumerate(vector_specs)
            ],
        ),
        "graph_node_chunks": write_index(
            "graph_node_chunks",
            [
                meta_row(
                    node_path,
                    shard_id=0,
                    row_count=4,
                    first_key="node-commit-1",
                    last_key="node-file-1",
                    kind="graph_nodes",
                )
            ],
        ),
        "graph_outgoing_adjacency": write_index(
            "graph_outgoing_adjacency",
            [
                meta_row(
                    out_path,
                    shard_id=0,
                    row_count=4,
                    first_key="node-commit-1",
                    last_key="node-file-1",
                    kind="graph_outgoing_adjacency",
                    adjacency_count=4,
                    direction="outgoing",
                    first_page_index=0,
                    last_page_index=0,
                    node_count=4,
                )
            ],
        ),
        "graph_incoming_adjacency": write_index(
            "graph_incoming_adjacency",
            [
                meta_row(
                    in_path,
                    shard_id=0,
                    row_count=4,
                    first_key="node-commit-1",
                    last_key="node-file-1",
                    kind="graph_incoming_adjacency",
                    adjacency_count=4,
                    direction="incoming",
                    first_page_index=0,
                    last_page_index=0,
                    node_count=4,
                )
            ],
        ),
    }

    # Node keys must be sorted for key-range validation — rewrite node shard
    # in CID order so first_key/last_key match first/last rows.
    ordered_nodes = sorted(node_rows, key=lambda row: row["node_cid"])
    write_parquet(node_path, ordered_nodes)
    index_descriptors["graph_node_chunks"] = write_index(
        "graph_node_chunks",
        [
            meta_row(
                node_path,
                shard_id=0,
                row_count=4,
                first_key=ordered_nodes[0]["node_cid"],
                last_key=ordered_nodes[-1]["node_cid"],
                kind="graph_nodes",
            )
        ],
    )
    ordered_out = sorted(out_rows, key=lambda row: row["node_cid"])
    write_parquet(out_path, ordered_out)
    index_descriptors["graph_outgoing_adjacency"] = write_index(
        "graph_outgoing_adjacency",
        [
            meta_row(
                out_path,
                shard_id=0,
                row_count=4,
                first_key=ordered_out[0]["node_cid"],
                last_key=ordered_out[-1]["node_cid"],
                kind="graph_outgoing_adjacency",
                adjacency_count=4,
                direction="outgoing",
                first_page_index=0,
                last_page_index=0,
                node_count=4,
            )
        ],
    )
    ordered_in = sorted(in_rows, key=lambda row: row["node_cid"])
    write_parquet(in_path, ordered_in)
    index_descriptors["graph_incoming_adjacency"] = write_index(
        "graph_incoming_adjacency",
        [
            meta_row(
                in_path,
                shard_id=0,
                row_count=4,
                first_key=ordered_in[0]["node_cid"],
                last_key=ordered_in[-1]["node_cid"],
                kind="graph_incoming_adjacency",
                adjacency_count=4,
                direction="incoming",
                first_page_index=0,
                last_page_index=0,
                node_count=4,
            )
        ],
    )

    artifacts = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        if path.name == DEFAULT_MANIFEST:
            continue
        relative = path.relative_to(root).as_posix()
        content = path.read_bytes()
        digest = hashlib.sha256(content).digest()
        artifacts.append(
            {
                "byte_length": len(content),
                "content_id": _raw_sha256_cid(digest),
                "media_type": (
                    "application/vnd.apache.parquet"
                    if path.suffix == ".parquet"
                    else "application/octet-stream"
                ),
                "path": relative,
                "sha256": digest.hex(),
            }
        )

    manifest = {
        "artifacts": artifacts,
        "bm25": {
            "average_document_length": 5.0,
            "b": 0.75,
            "body_weight": 1.0,
            "k1": 1.2,
            "max_query_terms": 64,
            "title_weight": 5.0,
            "tokenizer": BM25_TOKENIZER,
        },
        "counts": {
            "corpus_rows": 2,
            "graph_data_shards": 4,
            "graph_edges": 3,
            "graph_nodes": 4,
            "original_data_rows": 1,
            "vector_rows": 2,
        },
        "dataset_id": "Publicus/cvefixes-security-ir-graphrag",
        "derived_dataset_root": "bafkreia74ozdbgzwnirt7mixgfwwffiku24vbtwmivzyvvyghlgqhvkwk4",
        "graph": {
            "adjacency": "incoming_and_outgoing_bounded_pages",
            "edge_count": 3,
            "graph_root": EXPECTED_PROVENANCE["graph_root_cid"],
            "node_count": 4,
            "ontology_version": "cvefixes-graphrag-ontology/v1",
        },
        "indexes": index_descriptors,
        "primary_key": "entry_cid",
        "release_root": "bafkreiaoirr52so2im23swotylyffivoubcuhvumr2oei3s3sk2v6f4vly",
        "schema_version": "cvefixes-huggingface-release/v1",
        "source": {
            "dataset_id": EXPECTED_PROVENANCE["source_dataset_id"],
            "license_expression": EXPECTED_PROVENANCE["license_expression"],
            "source_revision": EXPECTED_PROVENANCE["source_revision"],
        },
        "vector": {
            "default_probe_centroids": 1,
            "dimension": 2,
            "layout": "semantic_centroid_groups",
            "max_shards_per_centroid": 2,
            "model_config_cid": model_config_cid,
            "model_id": "test/model",
            "model_name": f"test/model@{model_revision}",
            "model_revision": model_revision,
            "neutral_rows": 0,
            "searchable": True,
        },
    }
    (root / DEFAULT_MANIFEST).write_text(
        json.dumps(manifest, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    return root


__all__ = [
    "ArtifactResolver",
    "BM25_TOKENIZER",
    "CVEfixesAdapterError",
    "CVEfixesCorpusAdapter",
    "CVEfixesRemoteIndex",
    "DEFAULT_BUILD_ROOT",
    "DEFAULT_MANIFEST",
    "DEFAULT_REPO_ID",
    "ENV_RELEASE_ROOT",
    "ENV_SOURCE_ROOT",
    "EXPECTED_FULL_COUNTS",
    "EXPECTED_PROVENANCE",
    "LOCAL_FIXTURE_REVISION",
    "META_SCHEMA_VERSION",
    "RemoteQueryError",
    "build_tiny_fixture_release",
    "differential_query_parity",
    "discover_build_root",
    "discover_release_root",
    "discover_source_root",
    "find_nodes_by_type",
    "load_legacy_query_module",
    "open_release_reader",
    "traverse_cve_neighborhood",
    "validate_graph_and_vector_shards",
    "validate_manifest",
    "validate_source_parquet",
]

