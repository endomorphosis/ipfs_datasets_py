#!/usr/bin/env python3
"""Query the indexed CVEfixes Security IR release without a full download.

The client mirrors the remote-index layout used by ``Publicus/skillcenter-ir``:

* BM25 terms route through ``indexes/bm25_keyword_shards.parquet``;
* vector queries route through centroids in ``indexes/vector_chunks.parquet``;
* graph queries route through bounded incoming/outgoing adjacency indexes; and
* final retrieval rows hydrate through ``indexes/corpus_chunks.parquet``.

Remote queries require an immutable 40-character Hugging Face commit revision.
Every selected index and data shard is validated by SHA-256, raw-file CID,
byte size, row count, and its declared key/document range before use. Tokens
are read only from ``HF_TOKEN`` and are never accepted as command arguments or
included in query output.
"""

from __future__ import annotations

import argparse
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


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Query the pinned CVEfixes Security IR BM25/vector/graph "
            "Parquet release without downloading the complete dataset"
        )
    )
    parser.add_argument("--repo-id", default=DEFAULT_REPO_ID)
    parser.add_argument(
        "--revision",
        required=True,
        help="Required immutable 40-character Hugging Face commit SHA.",
    )
    parser.add_argument("--path-prefix", default="")
    parser.add_argument("--manifest", default=DEFAULT_MANIFEST)
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE_DIR)
    parser.add_argument(
        "--local-root",
        type=Path,
        default=None,
        help="Query a local staged release while retaining revision validation.",
    )
    parser.add_argument(
        "--no-content",
        action="store_true",
        help="Return identity/lineage columns without large corpus text fields.",
    )
    modes = parser.add_subparsers(dest="mode", required=True)

    bm25 = modes.add_parser("bm25", help="BM25 keyword retrieval")
    bm25.add_argument("query")
    bm25.add_argument("--top-k", type=int, default=10)

    vector = modes.add_parser(
        "vector", help="Centroid-routed vector retrieval"
    )
    vector.add_argument("query")
    vector.add_argument("--top-k", type=int, default=10)
    vector.add_argument("--candidate-centroids", type=int, default=None)
    vector.add_argument("--max-vector-shards", type=int, default=8)
    vector.add_argument(
        "--query-vector-json",
        default=None,
        help="JSON array or file path; skips local model inference.",
    )
    vector.add_argument(
        "--device",
        choices=["cuda", "cpu"],
        default="cuda",
        help="Local embedding device. CUDA is the fail-closed default.",
    )
    vector.add_argument(
        "--model",
        default=None,
        help="Optional assertion that must match manifest vector.model_name.",
    )
    vector.add_argument("--allow-exhaustive", action="store_true")

    graph = modes.add_parser(
        "graph", help="Bounded CID-based graph queries"
    )
    graph_modes = graph.add_subparsers(dest="graph_mode", required=True)
    graph_node = graph_modes.add_parser("node", help="Resolve one graph node")
    graph_node.add_argument("node_cid")
    neighbors = graph_modes.add_parser(
        "neighbors", help="Fetch a bounded adjacency page"
    )
    neighbors.add_argument("node_cid")
    neighbors.add_argument(
        "--direction",
        choices=["incoming", "outgoing", "both"],
        default="both",
    )
    neighbors.add_argument("--limit", type=int, default=50)
    neighbors.add_argument("--offset", type=int, default=0)
    neighbors.add_argument(
        "--edge-type", action="append", default=[], dest="edge_types"
    )
    neighbors.add_argument("--hydrate", action="store_true")
    neighbors.add_argument("--max-shards", type=int, default=64)
    walk = graph_modes.add_parser(
        "walk", help="Breadth-first graph walk with hard budgets"
    )
    walk.add_argument("start_node_cid")
    walk.add_argument(
        "--direction",
        choices=["incoming", "outgoing", "both"],
        default="outgoing",
    )
    walk.add_argument("--max-depth", type=int, default=2)
    walk.add_argument("--max-nodes", type=int, default=100)
    walk.add_argument("--max-edges", type=int, default=500)
    walk.add_argument("--per-node-limit", type=int, default=16)
    walk.add_argument("--max-shards", type=int, default=64)
    walk.add_argument(
        "--edge-type", action="append", default=[], dest="edge_types"
    )
    walk.add_argument("--hydrate", action="store_true")
    return parser


def _run(args: argparse.Namespace) -> dict[str, Any]:
    resolver = ArtifactResolver(
        repo_id=args.repo_id,
        revision=args.revision,
        path_prefix=args.path_prefix,
        token=os.environ.get("HF_TOKEN"),
        cache_dir=args.cache_dir,
        local_root=args.local_root,
    )
    index = CVEfixesRemoteIndex(resolver, manifest_path=args.manifest)
    if args.mode == "bm25":
        return index.bm25(
            args.query,
            top_k=args.top_k,
            include_content=not args.no_content,
        )
    if args.mode == "vector":
        model_name = _bound_model_name(index.manifest, args.model)
        if args.query_vector_json:
            query_vector = _read_query_vector(args.query_vector_json)
            embedding_device = "provided"
        else:
            model_name, model_id, model_revision = _embedding_model_binding(
                index.manifest, args.model
            )
            query_vector = _embed_query(
                args.query,
                model_id=model_id,
                model_revision=model_revision,
                device=args.device,
            )
            embedding_device = args.device
        result = index.vector(
            args.query,
            top_k=args.top_k,
            query_vector=query_vector,
            candidate_centroids=args.candidate_centroids,
            max_vector_shards=args.max_vector_shards,
            include_content=not args.no_content,
            allow_exhaustive=args.allow_exhaustive,
        )
        result["diagnostics"]["query_embedding_device"] = embedding_device
        result["diagnostics"]["query_embedding_model"] = model_name
        return result
    if args.graph_mode == "node":
        return index.graph_node(args.node_cid)
    if args.graph_mode == "neighbors":
        return index.graph_neighbors(
            args.node_cid,
            direction=args.direction,
            limit=args.limit,
            offset=args.offset,
            edge_types=args.edge_types,
            hydrate=args.hydrate,
            max_shards=args.max_shards,
        )
    return index.graph_walk(
        args.start_node_cid,
        direction=args.direction,
        max_depth=args.max_depth,
        max_nodes=args.max_nodes,
        max_edges=args.max_edges,
        per_node_limit=args.per_node_limit,
        max_shards=args.max_shards,
        edge_types=args.edge_types,
        hydrate=args.hydrate,
    )


def main(argv: Sequence[str] | None = None) -> int:
    try:
        result = _run(_parser().parse_args(argv))
    except RemoteQueryError as exc:
        json.dump(
            {"error": str(exc), "error_type": "RemoteQueryError"},
            sys.stderr,
            sort_keys=True,
        )
        sys.stderr.write("\n")
        return 2
    except Exception as exc:
        # Keep command-line failures credential-free even if a dependency
        # raises an unexpected exception containing request or cache details.
        json.dump(
            {
                "error": f"query failed safely ({type(exc).__name__})",
                "error_type": "RemoteQueryError",
            },
            sys.stderr,
            sort_keys=True,
        )
        sys.stderr.write("\n")
        return 2
    json.dump(result, sys.stdout, indent=2, sort_keys=True, ensure_ascii=False)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
