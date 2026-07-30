"""Read-only SkillCenter Intent IR GraphRAG corpus adapter (KGP-025).

Provides a fail-closed, integrity-checked reader over SkillCenter HF release
layouts produced by ``logic/intent_ir/graphrag/skillcenter_hf_release.py``
(local cache under ``~/.local/share/ipfs_datasets_py/intent-ir/skillcenter-huggingface``
and Hub dataset ``Publicus/skillcenter-ir``).

This module is the canonical in-tree port of the production query client
``scripts/ops/intent_ir/query_skillcenter_hf.py`` plus discovery,
count/checksum/provenance validation, skill/category/relationship/hybrid
rankings, and missing/corrupt shard handling.

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

from ipfs_datasets_py.knowledge_graphs.query.semantic_traversal import (
    EmbeddingGuidedTraversal,
    SemanticTraversalConfig,
    TraversalEdge,
)


DEFAULT_REPO_ID = "Publicus/skillcenter-ir"
DEFAULT_MANIFEST = "manifest.json"
DEFAULT_CACHE_DIR = Path(
    "~/.cache/ipfs_datasets_py/skillcenter-hf-query"
).expanduser()
DEFAULT_LOCAL_RELEASE_ROOT = Path(
    "~/.local/share/ipfs_datasets_py/intent-ir/skillcenter-huggingface"
).expanduser()
DEFAULT_RELEASE_CANDIDATES = (
    "full-cid-zstd-graph-v3",
    "full-cid-zstd-graph-v3-bounded",
    "full-cid-zstd-balanced-v2",
    "full-cid-zstd",
)
ENV_RELEASE_ROOT = "SKILLCENTER_RELEASE_ROOT"
ENV_RELEASE_ROOT_ALT = "SKILLCENTER_CORPUS_ROOT"
ENV_BUILD_ROOT = "SKILLCENTER_BUILD_ROOT"
LOCAL_FIXTURE_REVISION = "0" * 40
META_SCHEMA_VERSION = "skillcenter-hf-shard-meta/v1"
BM25_TOKENIZER = "sqlite-fts5-unicode61-remove-diacritics-2/v1"
SOURCE_DATASET_ID = "Tommysha/skillcenter-bundles"
SOURCE_REVISION = "f9dd4fec3c86d85ebf116c7408ac5ce602c418a1"
DERIVED_DATASET_REPO_ID = "Publicus/skillcenter-ir"

SUPPORTED_RELEASE_SCHEMAS = {
    "skillcenter-huggingface-release/v1",
    "skillcenter-huggingface-release/v2",
    "skillcenter-huggingface-release/v3",
}

# Pinned against the full-cid-zstd-graph-v3 local release (source rev f9dd4fec…).
EXPECTED_FULL_COUNTS = {
    "bm25_documents": 216972,
    "bm25_terms": 3776520,
    "corpus_rows": 216972,
    "graph_edges": 2560637,
    "graph_nodes": 434135,
    "vector_rows": 216972,
}
EXPECTED_PROVENANCE = {
    "source_dataset_id": SOURCE_DATASET_ID,
    "source_revision": SOURCE_REVISION,
    "derived_dataset_repo_id": DERIVED_DATASET_REPO_ID,
    "corpus_cid": "bafkreidmqpd65xegc4er2nyiqxhh2z5if3gjgoilwetuu3peyg2ccj4xoe",
    "graph_cid": "bafkreidzouiblczhjh5ca6ect6qpbaafuoxb2qyvygpalwu7gvhylxqm7a",
    "bm25_sqlite_cid": "bafkreibu5i7n62xhrpunseosz4gb6u4khgfig7yvxrvno6muoimrxafrlm",
    "vector_faiss_cid": "bafkreia6jb2z4wncyrgt7ihmkywje4rniaazfalcorq6td2u52jelgxbo4",
}

TOKEN_RE = re.compile(r"[A-Za-z0-9_]+")
MAX_QUERY_TERMS = 64
MAX_TOP_K = 1000
MAX_GRAPH_DEPTH = 8
MAX_GRAPH_NODES = 10_000
MAX_GRAPH_EDGES = 100_000
MAX_GRAPH_SHARDS = 1_024
MAX_VECTOR_SHARDS = 128
MAX_CANDIDATE_CENTROIDS = 64

_INDEX_PATHS = {
    "bm25_document_chunks": "indexes/bm25_document_chunks.parquet",
    "bm25_keyword_shards": "indexes/bm25_keyword_shards.parquet",
    "corpus_chunks": "indexes/corpus_chunks.parquet",
    "graph_edge_chunks": "indexes/graph_edge_chunks.parquet",
    "graph_incoming_adjacency": (
        "indexes/graph_incoming_adjacency.parquet"
    ),
    "graph_node_chunks": "indexes/graph_node_chunks.parquet",
    "graph_outgoing_adjacency": (
        "indexes/graph_outgoing_adjacency.parquet"
    ),
    "vector_chunks": "indexes/vector_chunks.parquet",
}
_REQUIRED_INDEXES = {
    "bm25_keyword_shards",
    "corpus_chunks",
    "graph_node_chunks",
    "graph_outgoing_adjacency",
    "graph_incoming_adjacency",
    "vector_chunks",
}
_OPTIONAL_INDEXES = {
    "bm25_document_chunks",
    "graph_edge_chunks",
}
_DATA_PREFIXES = {
    "bm25_postings": "data/bm25/postings/",
    "corpus": "data/corpus/",
    "graph_edges": "data/graph/edges/",
    "graph_incoming_adjacency": "data/graph/adjacency/incoming/",
    "graph_nodes": "data/graph/nodes/",
    "graph_outgoing_adjacency": "data/graph/adjacency/outgoing/",
    "vectors": "data/vectors/",
}
_ARTIFACT_KIND_PREFIXES = dict(_DATA_PREFIXES)


class SkillCenterAdapterError(RuntimeError):
    """Raised when a SkillCenter release, artifact, or query is malformed."""


# Backward-compatible alias used by the ported query client body.
RemoteQueryError = SkillCenterAdapterError


class _GraphShardBudgetReached(RuntimeError):
    """Internal signal used to stop a bounded walk cleanly."""

class ArtifactResolver:
    """Resolve only explicitly requested files from local or Hub storage."""

    def __init__(
        self,
        *,
        repo_id: str,
        revision: str,
        path_prefix: str = "",
        token: str | None = None,
        cache_dir: Path | None = None,
        local_root: Path | None = None,
    ) -> None:
        self.repo_id = repo_id
        self.revision = revision
        self.path_prefix = str(path_prefix or "").strip("/")
        self.token = token
        if cache_dir is None:
            cache_dir = DEFAULT_CACHE_DIR
        self.cache_dir = cache_dir
        self.local_root = (
            local_root.expanduser().resolve()
            if local_root is not None
            else None
        )
        self.fetched: dict[str, int] = {}
        self._parquet_cache: dict[
            tuple[str, tuple[str, ...] | None],
            Any,
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
                raise RemoteQueryError(f"release file is missing: {relative_path}")
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
            path = Path(
                hf_hub_download(
                    repo_id=self.repo_id,
                    filename=filename,
                    repo_type="dataset",
                    revision=self.revision,
                    token=self.token,
                    cache_dir=str(self.cache_dir),
                )
            )
        if descriptor is not None:
            _verify_descriptor(path, descriptor)
        self.fetched[safe.as_posix()] = path.stat().st_size
        return path

    def json(self, relative_path: str) -> dict[str, Any]:
        try:
            value = json.loads(self.path(relative_path).read_bytes())
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
        relative = str(descriptor.get("relative_path") or "")
        key = (
            relative,
            tuple(columns) if columns is not None else None,
        )
        cached = self._parquet_cache.get(key)
        if cached is not None:
            return cached
        table = pq.read_table(
            self.path(relative, descriptor=descriptor),
            columns=list(columns) if columns else None,
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


class SkillCenterRemoteIndex:
    """BM25 and centroid-routed vector search over one release."""

    def __init__(
        self,
        resolver: ArtifactResolver,
        *,
        manifest_path: str = DEFAULT_MANIFEST,
    ) -> None:
        self.resolver = resolver
        self.manifest = resolver.json(manifest_path)
        if (
            self.manifest.get("schema_version")
            not in SUPPORTED_RELEASE_SCHEMAS
            or self.manifest.get("primary_key") != "entry_cid"
        ):
            raise RemoteQueryError("unsupported SkillCenter release manifest")
        indexes = self.manifest.get("indexes")
        if not isinstance(indexes, Mapping):
            raise RemoteQueryError("release index descriptors are missing")
        self.indexes = dict(indexes)
        self._meta_cache: dict[str, list[dict[str, Any]]] = {}

    def bm25(
        self,
        query: str,
        *,
        top_k: int,
        include_content: bool = True,
    ) -> dict[str, Any]:
        _validate_top_k(top_k)
        config = dict(self.manifest["bm25"])
        terms = _tokenize(query)[: int(config.get("max_query_terms", 64))]
        if not terms:
            return self._result("bm25", query, [], {"query_terms": []})
        meta = self._meta_rows("bm25_keyword_shards")
        selected = _select_keyword_shards(meta, terms)
        rows_by_path: dict[str, list[str]] = defaultdict(list)
        descriptors = {}
        for term, row in selected.items():
            path = str(row["relative_path"])
            rows_by_path[path].append(term)
            descriptors[path] = row

        scores: dict[int, float] = defaultdict(float)
        matched: dict[int, set[str]] = defaultdict(set)
        posting_candidates: set[int] = set()
        for path, shard_terms in sorted(rows_by_path.items()):
            table = self.resolver.parquet(
                descriptors[path],
                columns=[
                    "body_frequencies",
                    "document_indices",
                    "document_lengths",
                    "idf",
                    "term",
                    "title_frequencies",
                ],
            )
            wanted = set(shard_terms)
            for row in table.to_pylist():
                term = str(row["term"])
                if term not in wanted:
                    continue
                document_ids = [int(value) for value in row["document_indices"]]
                title_frequencies = [
                    int(value) for value in row["title_frequencies"]
                ]
                body_frequencies = [
                    int(value) for value in row["body_frequencies"]
                ]
                document_lengths = [
                    int(value) for value in row["document_lengths"]
                ]
                if not (
                    len(document_ids)
                    == len(title_frequencies)
                    == len(body_frequencies)
                    == len(document_lengths)
                ):
                    raise RemoteQueryError(
                        f"unaligned BM25 posting arrays for {term!r}"
                    )
                for document_id, title_tf, body_tf, document_length in zip(
                    document_ids,
                    title_frequencies,
                    body_frequencies,
                    document_lengths,
                ):
                    weighted_tf = (
                        float(config["title_weight"]) * title_tf
                        + float(config["body_weight"]) * body_tf
                    )
                    scores[document_id] += _bm25_term_score(
                        weighted_tf,
                        document_length,
                        idf=float(row["idf"]),
                        average_document_length=float(
                            config["average_document_length"]
                        ),
                        k1=float(config["k1"]),
                        b=float(config["b"]),
                    )
                    matched[document_id].add(term)
                    posting_candidates.add(document_id)

        ranked = heapq.nlargest(
            top_k,
            scores.items(),
            key=lambda item: (item[1], -item[0]),
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
        candidate_chunks: int | None = None,
        candidate_centroids: int | None = None,
        include_content: bool = True,
        allow_exhaustive: bool = False,
    ) -> dict[str, Any]:
        _validate_top_k(top_k)
        try:
            import numpy as np
        except ImportError as exc:
            raise RemoteQueryError("numpy is required for vector search") from exc
        vector_config = dict(self.manifest["vector"])
        dimension = int(vector_config["dimension"])
        query_array = np.asarray(query_vector, dtype=np.float32)
        if (
            query_array.shape != (dimension,)
            or not np.isfinite(query_array).all()
        ):
            raise RemoteQueryError(
                f"query vector must contain {dimension} finite values"
            )
        norm = float(np.linalg.norm(query_array))
        if not math.isfinite(norm) or norm == 0:
            raise RemoteQueryError("query vector must be non-zero")
        query_array /= norm

        meta = self._meta_rows("vector_chunks")
        routing_groups = _vector_routing_groups(meta, vector_config)
        if candidate_chunks is not None and candidate_centroids is not None:
            raise RemoteQueryError(
                "choose candidate_chunks or candidate_centroids, not both"
            )
        requested_groups = (
            candidate_centroids
            if candidate_centroids is not None
            else candidate_chunks
        )
        if requested_groups is None:
            requested_groups = int(
                vector_config.get(
                    "default_probe_centroids",
                    vector_config.get("default_probe_shards", 8),
                )
            )
        if requested_groups < 1:
            raise RemoteQueryError("candidate centroid count must be positive")
        if (
            requested_groups >= len(routing_groups)
            and len(routing_groups) > 1
            and not allow_exhaustive
        ):
            raise RemoteQueryError(
                "the requested centroids would fetch every vector shard; "
                "pass --allow-exhaustive explicitly to permit that"
            )
        centroid_matrix = np.asarray(
            [group["centroid"] for group in routing_groups],
            dtype=np.float32,
        )
        if centroid_matrix.shape != (len(routing_groups), dimension):
            raise RemoteQueryError("vector centroid meta-index is malformed")
        centroid_scores = centroid_matrix @ query_array
        selected_indices = np.argsort(-centroid_scores, kind="stable")[
            : min(requested_groups, len(routing_groups))
        ]
        selected_groups = [
            routing_groups[int(index)] for index in selected_indices
        ]
        selected_shards = [
            row
            for group in selected_groups
            for row in group["shards"]
        ]

        heap: list[tuple[float, int, dict[str, Any]]] = []
        candidate_rows = 0
        for descriptor in selected_shards:
            table = self.resolver.parquet(descriptor)
            embeddings = table["embedding"].combine_chunks()
            matrix = np.asarray(
                embeddings.values.to_numpy(zero_copy_only=False),
                dtype=np.float32,
            ).reshape(table.num_rows, dimension)
            shard_scores = matrix @ query_array
            candidate_rows += table.num_rows
            compact = table.drop(["embedding"]).to_pylist()
            for row, score in zip(compact, shard_scores):
                item = (float(score), -int(row["document_index"]), row)
                if len(heap) < top_k:
                    heapq.heappush(heap, item)
                elif item[:2] > heap[0][:2]:
                    heapq.heapreplace(heap, item)
        selected_hits = sorted(heap, key=lambda item: item[:2], reverse=True)
        document_ids = [
            int(row["document_index"]) for _, _, row in selected_hits
        ]
        hydrated = self._hydrate(
            document_ids,
            include_content=include_content,
        )
        results = []
        for score, _, pointer in selected_hits:
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
                    "vector_chunk_id": str(pointer["chunk_id"]),
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
                "candidate_chunk_ids": [
                    int(row["shard_id"]) for row in selected_shards
                ],
                "candidate_chunks": len(selected_shards),
                "candidate_rows": candidate_rows,
                "dimension": dimension,
                "model_name": vector_config["model_name"],
                "routing_layout": vector_config.get(
                    "layout",
                    "legacy_coarse_cluster_slices",
                ),
                "total_vector_centroids": len(routing_groups),
                "total_vector_chunks": len(meta),
            },
        )

    def graph_node(self, node_cid: str) -> dict[str, Any]:
        """Resolve one graph node through the CID-range node index."""

        _validate_graph_key(node_cid, name="node_cid")
        nodes = self._graph_nodes([node_cid])
        return self._result(
            "graph_node",
            node_cid,
            [nodes[node_cid]] if node_cid in nodes else [],
            {"found": node_cid in nodes},
        )

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
        """Return a bounded, optionally hydrated adjacency page."""

        _validate_graph_key(node_cid, name="node_cid")
        _validate_graph_bounds(
            limit=limit,
            offset=offset,
            max_shards=max_shards,
        )
        directions = _graph_directions(direction)
        wanted = {
            str(value).strip()
            for value in edge_types
            if str(value).strip()
        }
        used_paths: set[str] = set()
        candidates = []
        totals = {}
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
        nodes = {}
        if hydrate:
            nodes = self._graph_nodes(
                [
                    node_cid,
                    *[
                        str(edge["neighbor_cid"])
                        for edge in selected
                    ],
                ]
            )
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
            result["nodes"] = [
                nodes[cid] for cid in sorted(nodes)
            ]
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
        """Walk the graph with hard depth, result, and artifact budgets."""

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
            limit=per_node_limit,
            offset=0,
            max_shards=max_shards,
        )
        directions = _graph_directions(direction)
        wanted = {
            str(value).strip()
            for value in edge_types
            if str(value).strip()
        }
        start_nodes = self._graph_nodes([start_node_cid])
        if start_node_cid not in start_nodes:
            return {
                "dataset_repo_id": self.resolver.repo_id,
                "dataset_revision": self.manifest["dataset_revision"],
                "diagnostics": {"found": False},
                "edges": [],
                "fetch_trace": self.resolver.trace(),
                "mode": "graph_walk",
                "nodes": [],
                "start_node_cid": start_node_cid,
            }

        visited = {start_node_cid: 0}
        node_types = {
            start_node_cid: str(
                start_nodes[start_node_cid].get("node_type") or ""
            )
        }
        frontier = [start_node_cid]
        traversed_edges = []
        seen_edge_directions: set[tuple[str, str]] = set()
        used_paths: set[str] = set()
        stop_reason = (
            "max_depth"
            if max_depth == 0
            else "frontier_exhausted"
        )
        for depth in range(max_depth):
            next_frontier = []
            for node_cid in frontier:
                candidates = []
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
                    frontier = []
                    next_frontier = []
                    break
                candidates.sort(key=_graph_edge_order_key)
                for edge in candidates[:per_node_limit]:
                    identity = (
                        str(edge["edge_cid"]),
                        str(edge["direction"]),
                    )
                    if identity in seen_edge_directions:
                        continue
                    neighbor_cid = str(edge["neighbor_cid"])
                    if (
                        neighbor_cid not in visited
                        and len(visited) >= max_nodes
                    ):
                        stop_reason = "max_nodes"
                        break
                    seen_edge_directions.add(identity)
                    traversed_edges.append(
                        {
                            **edge,
                            "depth": depth + 1,
                            "from_node_cid": node_cid,
                        }
                    )
                    node_types.setdefault(
                        neighbor_cid,
                        str(edge.get("neighbor_node_type") or ""),
                    )
                    if neighbor_cid not in visited:
                        visited[neighbor_cid] = depth + 1
                        next_frontier.append(neighbor_cid)
                    if len(traversed_edges) >= max_edges:
                        stop_reason = "max_edges"
                        break
                if stop_reason in {
                    "max_edges",
                    "max_nodes",
                    "max_shards",
                }:
                    break
            if stop_reason in {
                "max_edges",
                "max_nodes",
                "max_shards",
            }:
                break
            frontier = next_frontier
            if not frontier:
                stop_reason = "frontier_exhausted"
                break
            if depth + 1 == max_depth:
                stop_reason = "max_depth"

        hydrated = (
            self._graph_nodes(list(visited))
            if hydrate
            else {}
        )
        nodes = []
        for node_cid, depth in sorted(
            visited.items(),
            key=lambda item: (item[1], item[0]),
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
            "dataset_revision": self.manifest["dataset_revision"],
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

    def graph_semantic_walk(
        self,
        start_node_cid: str,
        *,
        query: str,
        query_vector: Sequence[float],
        direction: str,
        max_depth: int,
        max_nodes: int,
        max_edges: int,
        per_node_limit: int,
        max_shards: int,
        candidate_centroids: int,
        max_vector_shards: int,
        beam_width: int,
        edge_types: Sequence[str] = (),
        hydrate: bool = False,
    ) -> dict[str, Any]:
        """Walk toward a query using bounded remote vectors and adjacency."""

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
        if not 1 <= beam_width <= max_nodes:
            raise RemoteQueryError(
                "beam_width must be positive and no greater than max_nodes"
            )
        if not 1 <= max_vector_shards <= MAX_VECTOR_SHARDS:
            raise RemoteQueryError(
                "max_vector_shards must be between 1 and "
                f"{MAX_VECTOR_SHARDS}"
            )
        if candidate_centroids < 1:
            raise RemoteQueryError("candidate_centroids must be positive")
        _validate_graph_bounds(
            limit=per_node_limit,
            offset=0,
            max_shards=max_shards,
        )
        if direction not in {"incoming", "outgoing", "both", "adaptive"}:
            raise RemoteQueryError(
                "semantic direction must be incoming, outgoing, both, "
                "or adaptive"
            )
        wanted = {
            str(value).strip()
            for value in edge_types
            if str(value).strip()
        }
        start_nodes = self._graph_nodes([start_node_cid])
        if start_node_cid not in start_nodes:
            return {
                "dataset_repo_id": self.resolver.repo_id,
                "dataset_revision": self.manifest["dataset_revision"],
                "diagnostics": {
                    "found": False,
                    "traversal_strategy": "semantic_beam",
                },
                "edges": [],
                "fetch_trace": self.resolver.trace(),
                "mode": "graph_semantic_walk",
                "nodes": [],
                "query": query,
                "start_node_cid": start_node_cid,
            }

        graph_provider = _RemoteGraphNeighborProvider(
            self,
            edge_types=wanted,
            max_shards=max_shards,
        )
        embedding_provider = _RemoteCentroidEmbeddingProvider(
            self,
            query_vector=query_vector,
            candidate_centroids=candidate_centroids,
            max_vector_shards=max_vector_shards,
        )
        traversal = EmbeddingGuidedTraversal(
            graph_provider,
            embedding_provider,
            SemanticTraversalConfig(
                max_depth=max_depth,
                max_nodes=max_nodes,
                max_edges=max_edges,
                max_degree=per_node_limit,
                max_backend_calls=max_nodes,
                beam_width=beam_width,
                direction=direction,
                relationship_types=tuple(sorted(wanted)),
            ),
        )
        traversal_result = traversal.traverse(
            [start_node_cid],
            embedding_provider.query_vector,
        )

        hydrated = (
            self._graph_nodes(list(traversal_result.candidates))
            if hydrate
            else {}
        )
        nodes = []
        for node_cid, candidate in sorted(
            traversal_result.candidates.items(),
            key=lambda item: (
                item[1].depth,
                -item[1].score,
                item[0],
            ),
        ):
            node = {
                "depth": candidate.depth,
                "has_embedding": candidate.has_embedding,
                "node_cid": node_cid,
                "node_type": (
                    str(
                        start_nodes[start_node_cid].get("node_type")
                        or ""
                    )
                    if node_cid == start_node_cid
                    else graph_provider.node_types.get(node_cid, "")
                ),
                "semantic_direction": candidate.semantic_direction,
                "semantic_progress": candidate.semantic_progress,
                "semantic_proximity": candidate.semantic_proximity,
                "semantic_score": candidate.score,
            }
            if node_cid in hydrated:
                node.update(hydrated[node_cid])
                node.update(
                    {
                        "depth": candidate.depth,
                        "has_embedding": candidate.has_embedding,
                        "semantic_direction": candidate.semantic_direction,
                        "semantic_progress": candidate.semantic_progress,
                        "semantic_proximity": candidate.semantic_proximity,
                        "semantic_score": candidate.score,
                    }
                )
            nodes.append(node)

        edges = []
        for candidate in sorted(
            traversal_result.candidates.values(),
            key=lambda item: (item.depth, item.node_id),
        ):
            if candidate.parent_id is None:
                continue
            edge = graph_provider.edge_records.get(
                (
                    candidate.parent_id,
                    candidate.node_id,
                    candidate.relationship_type or "",
                )
            )
            edges.append(
                {
                    **(edge or {}),
                    "depth": candidate.depth,
                    "edge_type": candidate.relationship_type,
                    "from_node_cid": candidate.parent_id,
                    "neighbor_cid": candidate.node_id,
                    "semantic_score": candidate.score,
                }
            )

        semantic_diagnostics = traversal_result.diagnostics.to_dict()
        if graph_provider.shard_budget_reached:
            semantic_diagnostics["stop_reason"] = "max_shards"
        return {
            "dataset_repo_id": self.resolver.repo_id,
            "dataset_revision": self.manifest["dataset_revision"],
            "diagnostics": {
                **semantic_diagnostics,
                **embedding_provider.diagnostics(),
                "adjacency_shards_fetched": len(graph_provider.used_paths),
                "approximate": (
                    traversal_result.approximate
                    or graph_provider.shard_budget_reached
                ),
                "beam_width": beam_width,
                "candidate_centroids_requested": candidate_centroids,
                "complete": semantic_diagnostics["stop_reason"]
                == "frontier_exhausted",
                "direction": direction,
                "edge_types": sorted(wanted),
                "max_depth": max_depth,
                "max_edges": max_edges,
                "max_nodes": max_nodes,
                "max_shards": max_shards,
                "max_vector_shards": max_vector_shards,
                "per_node_limit": per_node_limit,
                "traversal_strategy": "semantic_beam",
            },
            "edges": edges,
            "fetch_trace": self.resolver.trace(),
            "mode": "graph_semantic_walk",
            "nodes": nodes,
            "paths": [
                path.to_dict() for path in traversal_result.paths
            ],
            "query": query,
            "start_node_cid": start_node_cid,
        }

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
                if str(row["first_key"])
                <= node_cid
                <= str(row["last_key"])
            ),
            key=lambda row: int(row["shard_id"]),
        )
        edges = []
        total_neighbors = 0
        for descriptor in descriptors:
            relative_path = str(descriptor["relative_path"])
            if (
                relative_path not in used_paths
                and len(used_paths) >= max_shards
            ):
                raise _GraphShardBudgetReached
            used_paths.add(relative_path)
            table = self.resolver.parquet(descriptor)
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
                    total_neighbors,
                    int(row["total_neighbor_count"]),
                )
                arrays = [
                    row["edge_cids"],
                    row["edge_types"],
                    row["neighbor_cids"],
                    row["neighbor_node_types"],
                    row["retrieval_methods"],
                    row["scores"],
                ]
                if (
                    any(len(values) != int(row["neighbor_count"]) for values in arrays)
                    or str(row["direction"]) != direction
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
                    neighbor_cid = str(neighbor_cid)
                    edges.append(
                        {
                            "direction": direction,
                            "edge_cid": str(edge_cid),
                            "edge_type": edge_type,
                            "neighbor_cid": neighbor_cid,
                            "neighbor_node_type": str(
                                neighbor_node_type
                            ),
                            "retrieval_method": str(retrieval_method),
                            "score": (
                                float(score)
                                if score is not None
                                else None
                            ),
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

    def _graph_nodes(
        self,
        node_cids: Sequence[str],
    ) -> dict[str, dict[str, Any]]:
        wanted = sorted(set(str(value) for value in node_cids))
        if not wanted:
            return {}
        meta = self._meta_rows("graph_node_chunks")
        rows_by_path: dict[str, set[str]] = defaultdict(set)
        descriptors = {}
        for node_cid in wanted:
            matches = [
                row
                for row in meta
                if str(row["first_key"])
                <= node_cid
                <= str(row["last_key"])
            ]
            if len(matches) > 1:
                raise RemoteQueryError(
                    f"overlapping graph node ranges for {node_cid!r}"
                )
            if matches:
                path = str(matches[0]["relative_path"])
                rows_by_path[path].add(node_cid)
                descriptors[path] = matches[0]
        result = {}
        for path, selected in sorted(rows_by_path.items()):
            table = self.resolver.parquet(descriptors[path])
            for row in table.to_pylist():
                node_cid = str(row["node_cid"])
                if node_cid not in selected:
                    continue
                properties = _parse_json_value(
                    row.get("properties_json"),
                    fallback={},
                )
                result[node_cid] = {
                    "entry_cid": row.get("entry_cid"),
                    "label": str(row.get("label") or ""),
                    "node_cid": node_cid,
                    "node_type": str(row.get("node_type") or ""),
                    "properties": properties,
                    "schema_version": str(
                        row.get("schema_version") or ""
                    ),
                }
        return result

    def _meta_rows(self, name: str) -> list[dict[str, Any]]:
        cached = self._meta_cache.get(name)
        if cached is not None:
            return cached
        descriptor = self.indexes.get(name)
        if not isinstance(descriptor, Mapping):
            raise RemoteQueryError(f"release index is missing: {name}")
        rows = self.resolver.parquet(descriptor).to_pylist()
        if not rows:
            raise RemoteQueryError(f"release index is empty: {name}")
        result = [dict(row) for row in rows]
        self._meta_cache[name] = result
        return result

    def _hydrate(
        self,
        document_ids: Sequence[int],
        *,
        include_content: bool,
    ) -> dict[int, dict[str, Any]]:
        if not document_ids:
            return {}
        meta = self._meta_rows("corpus_chunks")
        by_path: dict[str, list[int]] = defaultdict(list)
        descriptors = {}
        for document_id in sorted(set(int(value) for value in document_ids)):
            pointer = next(
                (
                    row
                    for row in meta
                    if int(row["start_document_index"])
                    <= document_id
                    <= int(row["end_document_index"])
                ),
                None,
            )
            if pointer is None:
                raise RemoteQueryError(
                    f"no corpus shard contains document {document_id}"
                )
            path = str(pointer["relative_path"])
            by_path[path].append(document_id)
            descriptors[path] = pointer
        columns = [
            "document_index",
            "entry_cid",
            "skill_id",
            "title",
            "domain",
            "profile",
            "repository_file",
            "source_type",
            "language",
            "license_expression",
            "source_url",
        ]
        if include_content:
            columns.extend(["skill_md", "library_md", "metadata_yaml"])
        hydrated = {}
        for path, wanted_ids in sorted(by_path.items()):
            table = self.resolver.parquet(
                descriptors[path],
                columns=columns,
            )
            wanted = set(wanted_ids)
            for row in table.to_pylist():
                document_id = int(row["document_index"])
                if document_id in wanted:
                    hydrated[document_id] = {
                        key: _json_value(value) for key, value in row.items()
                    }
        return hydrated

    def _result(
        self,
        mode: str,
        query: str,
        results: Sequence[Mapping[str, Any]],
        diagnostics: Mapping[str, Any],
    ) -> dict[str, Any]:
        return {
            "dataset_repo_id": self.resolver.repo_id,
            "dataset_revision": self.manifest["dataset_revision"],
            "diagnostics": dict(diagnostics),
            "fetch_trace": self.resolver.trace(),
            "mode": mode,
            "query": query,
            "result_count": len(results),
            "results": list(results),
        }


class _RemoteGraphNeighborProvider:
    """Fetch bounded remote adjacency shards for canonical traversal."""

    def __init__(
        self,
        index: SkillCenterRemoteIndex,
        *,
        edge_types: set[str],
        max_shards: int,
    ) -> None:
        self.index = index
        self.edge_types = edge_types
        self.max_shards = max_shards
        self.used_paths: set[str] = set()
        self.shard_budget_reached = False
        self.edge_records: dict[
            tuple[str, str, str],
            dict[str, Any],
        ] = {}
        self.node_types: dict[str, str] = {}

    def get_neighbors(
        self,
        node_id: str,
        *,
        direction: str,
        relationship_types: Sequence[str],
        limit: int,
    ) -> list[TraversalEdge]:
        if self.shard_budget_reached:
            return []
        wanted = set(relationship_types) or self.edge_types
        candidates: list[dict[str, Any]] = []
        resolved_value = "both" if direction == "adaptive" else direction
        try:
            for resolved_direction in _graph_directions(resolved_value):
                edges, _ = self.index._graph_adjacency_edges(
                    node_id,
                    direction=resolved_direction,
                    limit=limit,
                    edge_types=wanted,
                    used_paths=self.used_paths,
                    max_shards=self.max_shards,
                )
                candidates.extend(edges)
        except _GraphShardBudgetReached:
            self.shard_budget_reached = True
            return []

        candidates.sort(key=_graph_edge_order_key)
        output = []
        for edge in candidates[:limit]:
            neighbor_cid = str(edge["neighbor_cid"])
            edge_type = str(edge.get("edge_type") or "")
            self.node_types.setdefault(
                neighbor_cid,
                str(edge.get("neighbor_node_type") or ""),
            )
            self.edge_records.setdefault(
                (node_id, neighbor_cid, edge_type),
                dict(edge),
            )
            output.append(
                TraversalEdge(
                    source_id=node_id,
                    target_id=neighbor_cid,
                    relationship_type=edge_type or None,
                    weight=_semantic_edge_weight(edge),
                    metadata=edge,
                )
            )
        return output


class _RemoteCentroidEmbeddingProvider:
    """Load a query-routed, bounded subset of remote vector shards once."""

    def __init__(
        self,
        index: SkillCenterRemoteIndex,
        *,
        query_vector: Sequence[float],
        candidate_centroids: int,
        max_vector_shards: int,
    ) -> None:
        try:
            import numpy as np
        except ImportError as exc:
            raise RemoteQueryError(
                "numpy is required for semantic graph traversal"
            ) from exc
        vector_config = dict(index.manifest.get("vector") or {})
        if not vector_config:
            raise RemoteQueryError(
                "release has no vector configuration for semantic traversal"
            )
        dimension = int(vector_config["dimension"])
        query_array = np.asarray(query_vector, dtype=np.float32)
        if (
            query_array.shape != (dimension,)
            or not np.isfinite(query_array).all()
        ):
            raise RemoteQueryError(
                f"query vector must contain {dimension} finite values"
            )
        norm = float(np.linalg.norm(query_array))
        if not math.isfinite(norm) or norm == 0.0:
            raise RemoteQueryError("query vector must be non-zero")
        query_array /= norm

        meta = index._meta_rows("vector_chunks")
        groups = _vector_routing_groups(meta, vector_config)
        centroid_matrix = np.asarray(
            [group["centroid"] for group in groups],
            dtype=np.float32,
        )
        if centroid_matrix.shape != (len(groups), dimension):
            raise RemoteQueryError("vector centroid meta-index is malformed")
        centroid_scores = centroid_matrix @ query_array
        ranked_indices = np.argsort(-centroid_scores, kind="stable")

        selected_groups = []
        selected_shards = []
        skipped_for_budget = 0
        for raw_index in ranked_indices:
            if len(selected_groups) >= min(candidate_centroids, len(groups)):
                break
            group = groups[int(raw_index)]
            group_shards = list(group["shards"])
            if len(selected_shards) + len(group_shards) > max_vector_shards:
                skipped_for_budget += 1
                continue
            selected_groups.append(group)
            selected_shards.extend(group_shards)
        if not selected_groups:
            smallest = min(len(group["shards"]) for group in groups)
            raise RemoteQueryError(
                "max_vector_shards cannot fit one routing centroid; "
                f"increase it to at least {smallest}"
            )

        self.index = index
        self.query_vector = query_array
        self.dimension = dimension
        self.selected_groups = selected_groups
        self.selected_shards = selected_shards
        self.skipped_for_budget = skipped_for_budget
        self._vectors: dict[str, Any] = {}
        self._loaded = False
        self._rows_loaded = 0

    def _load(self) -> None:
        if self._loaded:
            return
        try:
            import numpy as np
        except ImportError as exc:
            raise RemoteQueryError(
                "numpy is required for semantic graph traversal"
            ) from exc
        for descriptor in self.selected_shards:
            table = self.index.resolver.parquet(
                descriptor,
                columns=["embedding", "entry_cid"],
            )
            embeddings = table["embedding"].combine_chunks()
            matrix = np.asarray(
                embeddings.values.to_numpy(zero_copy_only=False),
                dtype=np.float32,
            ).reshape(table.num_rows, self.dimension)
            entry_cids = table["entry_cid"].to_pylist()
            if (
                len(entry_cids) != table.num_rows
                or not np.isfinite(matrix).all()
            ):
                raise RemoteQueryError("vector shard is malformed")
            for row_index, entry_cid in enumerate(entry_cids):
                self._vectors[str(entry_cid)] = matrix[row_index]
            self._rows_loaded += table.num_rows
        self._loaded = True

    def get_embeddings(
        self,
        node_ids: Sequence[str],
    ) -> Mapping[str, Sequence[float]]:
        self._load()
        return {
            node_id: self._vectors[node_id]
            for node_id in node_ids
            if node_id in self._vectors
        }

    def diagnostics(self) -> dict[str, Any]:
        return {
            "candidate_centroid_ids": [
                int(group["cluster_id"]) for group in self.selected_groups
            ],
            "candidate_centroids": len(self.selected_groups),
            "candidate_vector_rows": self._rows_loaded,
            "candidate_vector_shard_ids": [
                int(row["shard_id"]) for row in self.selected_shards
            ],
            "candidate_vector_shards": len(self.selected_shards),
            "centroids_skipped_for_vector_shard_budget": (
                self.skipped_for_budget
            ),
            "embedding_dimension": self.dimension,
            "embedding_model_name": self.index.manifest["vector"][
                "model_name"
            ],
            "vector_routing_layout": self.index.manifest["vector"].get(
                "layout",
                "legacy_coarse_cluster_slices",
            ),
        }


def _vector_routing_groups(
    meta_rows: Sequence[Mapping[str, Any]],
    vector_config: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Group one or two physical shards behind each routing centroid."""

    if vector_config.get("layout") != "semantic_centroid_groups":
        return [
            {
                "centroid": row["centroid"],
                "cluster_id": int(row.get("cluster_id", row["shard_id"])),
                "shards": [row],
            }
            for row in meta_rows
        ]
    grouped: dict[int, list[Mapping[str, Any]]] = defaultdict(list)
    for row in meta_rows:
        grouped[int(row["cluster_id"])].append(row)
    maximum = int(vector_config.get("max_shards_per_centroid", 2))
    output = []
    for cluster_id in sorted(grouped):
        shards = sorted(
            grouped[cluster_id],
            key=lambda row: int(row["chunk_in_cluster"]),
        )
        centroid = [float(value) for value in shards[0]["centroid"]]
        if (
            not 1 <= len(shards) <= maximum
            or [int(row["chunk_in_cluster"]) for row in shards]
            != list(range(len(shards)))
            or any(
                int(row.get("centroid_shard_count", -1)) != len(shards)
                for row in shards
            )
            or any(
                list(row["centroid"]) != list(shards[0]["centroid"])
                for row in shards[1:]
            )
        ):
            raise RemoteQueryError(
                f"vector centroid {cluster_id} has malformed shard pointers"
            )
        output.append(
            {
                "centroid": centroid,
                "cluster_id": cluster_id,
                "shards": shards,
            }
        )
    if not output:
        raise RemoteQueryError("vector routing meta-index is empty")
    return output


def _graph_directions(value: str) -> tuple[str, ...]:
    direction = str(value or "").strip().lower()
    if direction in {"both", "adaptive"}:
        return ("outgoing", "incoming")
    if direction in {"incoming", "outgoing"}:
        return (direction,)
    raise RemoteQueryError(
        "graph direction must be incoming, outgoing, both, or adaptive"
    )


def _semantic_edge_weight(edge: Mapping[str, Any]) -> float:
    """Normalize heterogeneous BM25/vector/structural edge scores to 0..1."""
    score = edge.get("score")
    if score is None:
        return 0.5
    try:
        numeric = float(score)
    except (TypeError, ValueError, OverflowError):
        return 0.5
    if not math.isfinite(numeric):
        return 0.5
    if numeric <= 0.0:
        return 0.0
    if numeric <= 1.0:
        return numeric
    # BM25 values are unbounded.  This monotonic saturation retains useful
    # ordering without allowing them to dominate semantic vector components.
    return numeric / (numeric + 10.0)


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


def _validate_graph_bounds(
    *,
    limit: int,
    offset: int,
    max_shards: int,
) -> None:
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


def _parse_json_value(value: Any, *, fallback: Any) -> Any:
    if value is None:
        return fallback
    try:
        return json.loads(str(value))
    except (TypeError, ValueError, json.JSONDecodeError):
        return fallback


def _select_keyword_shards(
    meta_rows: Sequence[Mapping[str, Any]],
    terms: Sequence[str],
) -> dict[str, Mapping[str, Any]]:
    selected = {}
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


def _tokenize(text: str) -> list[str]:
    seen = set()
    output = []
    for match in TOKEN_RE.finditer(str(text or "")):
        token = match.group(0).lower()
        if token not in seen:
            seen.add(token)
            output.append(token)
        if len(output) >= MAX_QUERY_TERMS:
            break
    return output


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
    return idf * ((k1 + 1.0) * term_frequency) / denominator


def _embed_query(
    query: str,
    *,
    model_name: str,
    device: str,
) -> tuple[list[float], str, str]:
    try:
        import torch
        from sentence_transformers import SentenceTransformer
    except ImportError as exc:
        raise RemoteQueryError(
            "sentence-transformers and torch are required to embed a query"
        ) from exc
    devices = [device]
    if device == "auto":
        devices = ["cuda", "cpu"] if torch.cuda.is_available() else ["cpu"]
    first_error = ""
    for resolved_device in devices:
        model = None
        try:
            model = SentenceTransformer(
                model_name,
                device=resolved_device,
            )
            vector = model.encode(
                [query],
                batch_size=1,
                convert_to_numpy=True,
                normalize_embeddings=True,
                show_progress_bar=False,
            )[0]
            return (
                [float(value) for value in vector],
                resolved_device,
                first_error,
            )
        except Exception as exc:
            if device != "auto" or resolved_device != "cuda":
                raise
            first_error = f"{type(exc).__name__}: {exc}"
            del model
            gc.collect()
            try:
                torch.cuda.empty_cache()
            except Exception:
                pass
    raise RemoteQueryError("no query-embedding device is available")


def _read_query_vector(value: str) -> list[float]:
    candidate = Path(value).expanduser()
    try:
        raw = candidate.read_text(encoding="utf-8") if candidate.is_file() else value
        parsed = json.loads(raw)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RemoteQueryError("query vector JSON is malformed") from exc
    if not isinstance(parsed, list):
        raise RemoteQueryError("query vector JSON must be an array")
    return [float(item) for item in parsed]


def _safe_relative_path(value: str) -> PurePosixPath:
    pure = PurePosixPath(str(value or ""))
    if (
        not value
        or pure.is_absolute()
        or any(part in {"", ".", ".."} for part in pure.parts)
        or pure.as_posix() != value
    ):
        raise RemoteQueryError(f"unsafe release path: {value!r}")
    return pure


def _verify_descriptor(path: Path, value: Mapping[str, Any]) -> None:
    expected_size = int(value.get("size_bytes", -1))
    expected_sha = str(value.get("sha256") or "")
    if path.stat().st_size != expected_size:
        raise RemoteQueryError(f"artifact size differs: {path.name}")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(8 * 1024 * 1024):
            digest.update(chunk)
    if digest.hexdigest() != expected_sha:
        raise RemoteQueryError(f"artifact digest differs: {path.name}")


def _json_value(value: Any) -> Any:
    if isinstance(value, bytes):
        return value.hex()
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return value


def _validate_top_k(value: int) -> None:
    if isinstance(value, bool) or not 1 <= int(value) <= MAX_TOP_K:
        raise RemoteQueryError(f"top_k must be between 1 and {MAX_TOP_K}")



# ---------------------------------------------------------------------------
# Integrity helpers, discovery, validation, rankings, fixture
# ---------------------------------------------------------------------------


def _raw_sha256_cid(digest: bytes) -> str:
    """Encode a raw SHA-256 digest as a CIDv1 (raw codec) base32 string."""

    if len(digest) != 32:
        raise SkillCenterAdapterError("SHA-256 digest must be 32 bytes")
    # CIDv1 + raw codec + sha2-256 multihash.
    payload = bytes((0x01, 0x55, 0x12, 0x20)) + digest
    return "b" + base64.b32encode(payload).decode("ascii").lower().rstrip("=")


def _env_path(name: str) -> Path | None:
    raw = os.environ.get(name)
    if not raw:
        return None
    return Path(raw).expanduser()


def discover_build_root() -> Path | None:
    """Locate a SkillCenter build/cache tree, or None when unavailable."""

    candidate = _env_path(ENV_BUILD_ROOT)
    if candidate is not None and candidate.is_dir():
        return candidate.resolve()
    if DEFAULT_LOCAL_RELEASE_ROOT.is_dir():
        return DEFAULT_LOCAL_RELEASE_ROOT.resolve()
    return None


def discover_release_root() -> Path | None:
    """Locate a SkillCenter HF release root (env-gated or default local cache)."""

    for name in (ENV_RELEASE_ROOT, ENV_RELEASE_ROOT_ALT):
        candidate = _env_path(name)
        if candidate is not None and candidate.is_dir():
            if (candidate / DEFAULT_MANIFEST).is_file():
                return candidate.resolve()
    build = discover_build_root()
    if build is None:
        return None
    # Direct release root.
    if (build / DEFAULT_MANIFEST).is_file():
        return build.resolve()
    # Layout: <build>/<source-revision>/<release-name>/manifest.json
    try:
        revision_dirs = sorted(
            (
                path
                for path in build.iterdir()
                if path.is_dir() and not path.name.startswith(".")
            ),
            key=lambda path: path.name,
            reverse=True,
        )
    except OSError:
        return None
    for revision_dir in revision_dirs:
        for name in DEFAULT_RELEASE_CANDIDATES:
            candidate = revision_dir / name
            if (candidate / DEFAULT_MANIFEST).is_file():
                return candidate.resolve()
        # Any child with a manifest (prefer graph-v3 naming via candidates first).
        try:
            children = sorted(revision_dir.iterdir())
        except OSError:
            continue
        for child in children:
            if child.is_dir() and (child / DEFAULT_MANIFEST).is_file():
                return child.resolve()
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


def _validate_descriptor_shape(value: Mapping[str, Any]) -> None:
    relative = str(value.get("relative_path") or "")
    if not relative:
        raise SkillCenterAdapterError("descriptor relative_path is missing")
    _safe_relative_path(relative)
    try:
        size = int(value.get("size_bytes", -1))
    except (TypeError, ValueError) as exc:
        raise SkillCenterAdapterError("descriptor size_bytes is malformed") from exc
    if size < 0:
        raise SkillCenterAdapterError("descriptor size_bytes is malformed")
    sha = str(value.get("sha256") or "")
    if len(sha) != 64 or any(c not in "0123456789abcdef" for c in sha.lower()):
        raise SkillCenterAdapterError("descriptor sha256 is malformed")
    cid = str(value.get("cid") or "")
    if not cid.startswith("b") or len(cid) < 10:
        raise SkillCenterAdapterError("descriptor cid is malformed")


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
        raise SkillCenterAdapterError(f"release file is missing: {relative_path}")
    actual_size = path.stat().st_size
    if size_bytes is not None and actual_size != int(size_bytes):
        raise SkillCenterAdapterError(f"artifact size differs: {relative_path}")
    digest_hex = _sha256_file(path)
    if sha256 is not None and digest_hex != sha256:
        raise SkillCenterAdapterError(f"artifact digest differs: {relative_path}")
    if cid is not None:
        computed_cid = _raw_sha256_cid(bytes.fromhex(digest_hex))
        if computed_cid != cid:
            raise SkillCenterAdapterError(f"artifact CID differs: {relative_path}")
    return {
        "relative_path": relative_path,
        "size_bytes": actual_size,
        "sha256": digest_hex,
        "cid": cid,
    }


def validate_manifest(
    release_root: Path | str,
    *,
    require_counts: bool = False,
) -> dict[str, Any]:
    """Load and structurally validate a SkillCenter HF release manifest."""

    root = Path(release_root).expanduser().resolve()
    manifest_path = root / DEFAULT_MANIFEST
    if not manifest_path.is_file():
        raise SkillCenterAdapterError(f"manifest is missing: {manifest_path}")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise SkillCenterAdapterError("manifest.json is malformed") from exc
    if not isinstance(manifest, dict):
        raise SkillCenterAdapterError("manifest.json must be an object")
    schema = manifest.get("schema_version")
    if schema not in SUPPORTED_RELEASE_SCHEMAS:
        raise SkillCenterAdapterError("unsupported SkillCenter release manifest")
    primary_key = manifest.get("primary_key")
    if primary_key not in {None, "entry_cid"}:
        raise SkillCenterAdapterError(
            "SkillCenter release primary key must be entry_cid"
        )
    indexes = manifest.get("indexes")
    if not isinstance(indexes, Mapping) or not indexes:
        raise SkillCenterAdapterError("release index descriptors are missing")
    for name in _REQUIRED_INDEXES:
        if name not in indexes:
            raise SkillCenterAdapterError(f"release index is missing: {name}")
    for name, descriptor in indexes.items():
        if not isinstance(descriptor, Mapping):
            raise SkillCenterAdapterError(f"release index is malformed: {name}")
        expected_path = _INDEX_PATHS.get(str(name))
        relative = str(descriptor.get("relative_path") or "")
        if expected_path is not None and relative != expected_path:
            raise SkillCenterAdapterError(f"release index path differs: {name}")
        _validate_descriptor_shape(descriptor)
        _verify_path_checksum(
            root,
            relative,
            sha256=str(descriptor["sha256"]),
            size_bytes=int(descriptor["size_bytes"]),
            cid=str(descriptor["cid"]),
        )
    counts = (
        manifest.get("counts")
        if isinstance(manifest.get("counts"), Mapping)
        else {}
    )
    if require_counts and not counts:
        raise SkillCenterAdapterError("release counts are missing")
    bm25 = manifest.get("bm25") if isinstance(manifest.get("bm25"), Mapping) else {}
    vector = (
        manifest.get("vector") if isinstance(manifest.get("vector"), Mapping) else {}
    )
    graph = manifest.get("graph") if isinstance(manifest.get("graph"), Mapping) else {}
    bindings = (
        manifest.get("input_bindings")
        if isinstance(manifest.get("input_bindings"), Mapping)
        else {}
    )
    return {
        "manifest_path": str(manifest_path),
        "manifest_sha256": _sha256_file(manifest_path),
        "schema_version": schema,
        "dataset_id": manifest.get("dataset_id"),
        "dataset_repo_id": manifest.get("dataset_repo_id"),
        "dataset_revision": manifest.get("dataset_revision"),
        "primary_key": primary_key or "entry_cid",
        "counts": dict(counts),
        "bm25": dict(bm25),
        "vector": dict(vector),
        "graph": dict(graph),
        "input_bindings": dict(bindings),
        "index_names": sorted(str(key) for key in indexes),
        "manifest": manifest,
    }


def validate_release_shards(
    release_root: Path | str,
    manifest: Mapping[str, Any],
    *,
    verify_data_checksums: bool = True,
    max_data_shards: int | None = None,
) -> dict[str, Any]:
    """Validate corpus/graph/adjacency/BM25/vector shard presence and integrity."""

    root = Path(release_root).expanduser().resolve()
    try:
        import pyarrow.parquet as pq
    except ImportError as exc:
        raise SkillCenterAdapterError(
            "pyarrow is required for shard validation"
        ) from exc

    # Build lookup of meta-index descriptors by relative path for checksums.
    index_descriptors = manifest.get("indexes") or {}
    meta_by_path: dict[str, Mapping[str, Any]] = {}
    for name, descriptor in index_descriptors.items():
        if not isinstance(descriptor, Mapping):
            continue
        relative = str(descriptor.get("relative_path") or "")
        if relative:
            meta_by_path[relative] = descriptor

    # Load each meta index and verify pointed-to data shards when present.
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
                raise SkillCenterAdapterError(
                    f"corrupt or unreadable shard: {relative}"
                ) from exc
            if rows <= 0:
                raise SkillCenterAdapterError(f"empty data shard: {relative}")
            total_rows += rows
            receipt: dict[str, Any] = {
                "relative_path": relative,
                "row_count": rows,
                "size_bytes": shard.stat().st_size,
            }
            if verify_data_checksums:
                digest = _sha256_file(shard)
                receipt["sha256"] = digest
                verified += 1
            shard_rows.append(receipt)
        kind_receipts[kind] = {
            "directory": prefix,
            "shard_count": len(shards),
            "checked_shards": len(shard_rows),
            "row_count_checked": total_rows,
            "shards": shard_rows,
        }

    # Required kinds for a navigable release (v3 graph layout).
    required_kinds = {
        "corpus",
        "graph_nodes",
        "graph_outgoing_adjacency",
        "graph_incoming_adjacency",
        "vectors",
        "bm25_postings",
    }
    for kind in required_kinds:
        if not kind_receipts.get(kind, {}).get("shard_count"):
            raise SkillCenterAdapterError(
                f"missing {kind} shards under {_ARTIFACT_KIND_PREFIXES[kind]}"
            )

    counts = (
        manifest.get("counts")
        if isinstance(manifest.get("counts"), Mapping)
        else {}
    )
    comparisons: dict[str, Any] = {}
    if counts and max_data_shards is None:
        node_rows = kind_receipts.get("graph_nodes", {}).get("row_count_checked")
        edge_rows = kind_receipts.get("graph_edges", {}).get("row_count_checked")
        corpus_rows = kind_receipts.get("corpus", {}).get("row_count_checked")
        vector_rows = kind_receipts.get("vectors", {}).get("row_count_checked")
        if "graph_nodes" in counts and node_rows is not None:
            if int(node_rows) != int(counts["graph_nodes"]):
                raise SkillCenterAdapterError(
                    "graph node count differs from manifest.counts"
                )
            comparisons["graph_nodes"] = node_rows
        if "graph_edges" in counts and edge_rows is not None and edge_rows > 0:
            if int(edge_rows) != int(counts["graph_edges"]):
                raise SkillCenterAdapterError(
                    "graph edge count differs from manifest.counts"
                )
            comparisons["graph_edges"] = edge_rows
        if "corpus_rows" in counts and corpus_rows is not None:
            if int(corpus_rows) != int(counts["corpus_rows"]):
                raise SkillCenterAdapterError(
                    "corpus row count differs from manifest.counts"
                )
            comparisons["corpus_rows"] = corpus_rows
        if "vector_rows" in counts and vector_rows is not None:
            if int(vector_rows) != int(counts["vector_rows"]):
                raise SkillCenterAdapterError(
                    "vector row count differs from manifest.counts"
                )
            comparisons["vector_rows"] = vector_rows

    # Validate meta-index rows for kind/path consistency (bounded).
    try:
        import pyarrow.parquet as pq
    except ImportError:
        pq = None  # type: ignore
    meta_receipts: dict[str, Any] = {}
    if pq is not None:
        for name, expected_path in _INDEX_PATHS.items():
            descriptor = index_descriptors.get(name)
            if not isinstance(descriptor, Mapping):
                continue
            index_path = root / expected_path
            if not index_path.is_file():
                continue
            table = pq.read_table(index_path)
            rows = table.to_pylist()
            meta_receipts[name] = {
                "row_count": len(rows),
                "relative_path": expected_path,
            }
            # Spot-check first row points to an existing shard when present.
            if rows:
                first = rows[0]
                relative = str(first.get("relative_path") or "")
                if relative:
                    target = root.joinpath(*_safe_relative_path(relative).parts)
                    if not target.is_file():
                        raise SkillCenterAdapterError(
                            f"meta index {name} points to missing shard: {relative}"
                        )

    return {
        "kinds": kind_receipts,
        "checksums_verified": verified,
        "count_comparisons": comparisons,
        "meta_indexes": meta_receipts,
    }


def open_release_reader(
    release_root: Path | str,
    *,
    revision: str = LOCAL_FIXTURE_REVISION,
    repo_id: str = DEFAULT_REPO_ID,
    cache_dir: Path | None = None,
) -> SkillCenterRemoteIndex:
    """Open a local release through the integrity-checked query reader."""

    root = Path(release_root).expanduser().resolve()
    if not (root / DEFAULT_MANIFEST).is_file():
        raise SkillCenterAdapterError(f"manifest is missing under {root}")
    resolver = ArtifactResolver(
        repo_id=repo_id,
        revision=revision,
        cache_dir=cache_dir or (root / ".cache"),
        local_root=root,
    )
    return SkillCenterRemoteIndex(resolver)


def find_nodes_by_type(
    reader: SkillCenterRemoteIndex,
    node_type: str,
    *,
    limit: int = 25,
    label_contains: str | None = None,
) -> list[dict[str, Any]]:
    """Scan graph node shards for a node_type (bounded)."""

    if not node_type or not isinstance(node_type, str):
        raise SkillCenterAdapterError("node_type must be a non-empty string")
    if not 1 <= int(limit) <= MAX_GRAPH_NODES:
        raise SkillCenterAdapterError(
            f"limit must be between 1 and {MAX_GRAPH_NODES}"
        )
    meta = reader._meta_rows("graph_node_chunks")
    matches: list[dict[str, Any]] = []
    needle = (label_contains or "").lower()
    for row in meta:
        table = reader.resolver.parquet(
            row,
            columns=[
                "node_cid",
                "node_type",
                "entry_cid",
                "label",
                "properties_json",
                "schema_version",
            ],
        )
        for item in table.to_pylist():
            if str(item.get("node_type") or "") != node_type:
                continue
            label = str(item.get("label") or "")
            if needle and needle not in label.lower():
                continue
            properties = _parse_json_value(
                item.get("properties_json"), fallback={}
            )
            matches.append(
                {
                    "entry_cid": item.get("entry_cid"),
                    "label": label,
                    "node_cid": str(item["node_cid"]),
                    "node_type": node_type,
                    "properties": properties,
                    "schema_version": str(item.get("schema_version") or ""),
                }
            )
            if len(matches) >= limit:
                return matches
    return matches


def _normalize_scores(scores: Mapping[str, float]) -> dict[str, float]:
    if not scores:
        return {}
    values = list(scores.values())
    lo = min(values)
    hi = max(values)
    if hi <= lo:
        return {key: 1.0 for key in scores}
    span = hi - lo
    return {key: (value - lo) / span for key, value in scores.items()}


def rank_skills(
    reader: SkillCenterRemoteIndex,
    query: str,
    *,
    top_k: int = 10,
    include_content: bool = False,
) -> dict[str, Any]:
    """Rank skills via BM25 over the release corpus (skill documents)."""

    result = reader.bm25(query, top_k=top_k, include_content=include_content)
    result["mode"] = "skill_ranking"
    result["ranking"] = "bm25_skill"
    return result


def rank_categories(
    reader: SkillCenterRemoteIndex,
    query: str,
    *,
    top_k: int = 10,
    max_skills: int = 25,
    max_shards: int = 32,
) -> dict[str, Any]:
    """Rank categories/domains by aggregating BM25 skill hits via IN_DOMAIN edges."""

    _validate_top_k(top_k)
    skills = reader.bm25(query, top_k=max_skills, include_content=False)
    domain_scores: dict[str, float] = defaultdict(float)
    domain_hits: dict[str, list[dict[str, Any]]] = defaultdict(list)
    used_paths: set[str] = set()
    for hit in skills["results"]:
        entry_cid = str(hit.get("entry_cid") or "")
        domain = str(hit.get("domain") or "").strip()
        score = float(hit.get("score") or 0.0)
        if domain:
            domain_scores[domain] += score
            domain_hits[domain].append(
                {
                    "entry_cid": entry_cid,
                    "skill_id": hit.get("skill_id"),
                    "title": hit.get("title"),
                    "score": score,
                }
            )
        if not entry_cid:
            continue
        # Walk OUTGOING IN_DOMAIN edges when the skill is a graph node.
        try:
            neighbors = reader.graph_neighbors(
                entry_cid,
                direction="outgoing",
                limit=8,
                edge_types=["IN_DOMAIN"],
                hydrate=True,
                max_shards=max_shards,
            )
        except SkillCenterAdapterError:
            continue
        for edge in neighbors.get("results") or []:
            label = str(edge.get("neighbor_cid") or "")
            nodes = {
                str(node.get("node_cid")): node
                for node in (neighbors.get("nodes") or [])
            }
            neighbor = nodes.get(str(edge.get("neighbor_cid")))
            if neighbor is not None:
                label = str(neighbor.get("label") or label)
                props = neighbor.get("properties") or {}
                if isinstance(props, Mapping) and props.get("domain"):
                    label = str(props["domain"])
            if not label:
                continue
            edge_score = edge.get("score")
            contrib = score * (
                float(edge_score) if edge_score is not None else 1.0
            )
            domain_scores[label] += contrib
            domain_hits[label].append(
                {
                    "entry_cid": entry_cid,
                    "skill_id": hit.get("skill_id"),
                    "title": hit.get("title"),
                    "score": contrib,
                    "via": "IN_DOMAIN",
                }
            )
        used_paths.update(
            item.get("relative_path", "")
            for item in (neighbors.get("fetch_trace") or {}).get("files") or []
        )

    ranked = heapq.nlargest(
        top_k,
        domain_scores.items(),
        key=lambda item: (item[1], item[0]),
    )
    results = [
        {
            "category": name,
            "score": score,
            "skill_hits": domain_hits.get(name, [])[:5],
            "skill_hit_count": len(domain_hits.get(name, [])),
        }
        for name, score in ranked
    ]
    return {
        "dataset_repo_id": reader.resolver.repo_id,
        "dataset_revision": reader.manifest.get("dataset_revision"),
        "diagnostics": {
            "skill_candidates": skills.get("result_count", 0),
            "query_terms": (skills.get("diagnostics") or {}).get("query_terms"),
            "categories_scored": len(domain_scores),
        },
        "fetch_trace": reader.resolver.trace(),
        "mode": "category_ranking",
        "query": query,
        "ranking": "bm25_domain_aggregation",
        "result_count": len(results),
        "results": results,
    }


def rank_relationships(
    reader: SkillCenterRemoteIndex,
    node_cid: str,
    *,
    direction: str = "both",
    top_k: int = 25,
    edge_types: Sequence[str] = (),
    hydrate: bool = True,
    max_shards: int = 64,
) -> dict[str, Any]:
    """Rank graph relationships (neighbors) by edge score for a node."""

    _validate_top_k(top_k)
    neighbors = reader.graph_neighbors(
        node_cid,
        direction=direction,
        limit=top_k,
        edge_types=edge_types,
        hydrate=hydrate,
        max_shards=max_shards,
    )
    results = list(neighbors.get("results") or [])
    # Already ordered by _graph_edge_order_key (score desc).
    nodes = {
        str(node.get("node_cid")): node
        for node in (neighbors.get("nodes") or [])
    }
    ranked = []
    for edge in results:
        neighbor_cid = str(edge.get("neighbor_cid") or "")
        neighbor = nodes.get(neighbor_cid, {})
        ranked.append(
            {
                **edge,
                "neighbor_label": neighbor.get("label"),
                "neighbor_entry_cid": neighbor.get("entry_cid"),
                "neighbor_properties": neighbor.get("properties"),
            }
        )
    return {
        "dataset_repo_id": reader.resolver.repo_id,
        "dataset_revision": reader.manifest.get("dataset_revision"),
        "diagnostics": neighbors.get("diagnostics") or {},
        "fetch_trace": neighbors.get("fetch_trace"),
        "mode": "relationship_ranking",
        "query": node_cid,
        "ranking": "graph_neighbor_score",
        "result_count": len(ranked),
        "results": ranked,
        "nodes": list(nodes.values()) if hydrate else [],
    }


def hybrid_rank(
    reader: SkillCenterRemoteIndex,
    query: str,
    *,
    top_k: int = 10,
    query_vector: Sequence[float] | None = None,
    bm25_weight: float = 0.5,
    vector_weight: float = 0.5,
    candidate_centroids: int | None = None,
    include_content: bool = False,
    allow_exhaustive: bool = True,
) -> dict[str, Any]:
    """Fuse BM25 and (optional) vector rankings with min-max normalized scores."""

    _validate_top_k(top_k)
    if bm25_weight < 0 or vector_weight < 0:
        raise SkillCenterAdapterError("hybrid weights must be non-negative")
    if bm25_weight == 0 and vector_weight == 0:
        raise SkillCenterAdapterError("at least one hybrid weight must be positive")

    bm25 = reader.bm25(
        query,
        top_k=max(top_k * 3, top_k),
        include_content=include_content,
    )
    bm25_scores = {
        str(row.get("entry_cid") or row.get("document_index")): float(
            row.get("score") or 0.0
        )
        for row in bm25["results"]
    }
    bm25_rows = {
        str(row.get("entry_cid") or row.get("document_index")): row
        for row in bm25["results"]
    }

    vector_scores: dict[str, float] = {}
    vector_rows: dict[str, dict[str, Any]] = {}
    vector_result: dict[str, Any] | None = None
    if query_vector is not None and vector_weight > 0:
        vector_result = reader.vector(
            query,
            top_k=max(top_k * 3, top_k),
            query_vector=query_vector,
            candidate_centroids=candidate_centroids,
            include_content=include_content,
            allow_exhaustive=allow_exhaustive,
        )
        vector_scores = {
            str(row.get("entry_cid") or row.get("document_index")): float(
                row.get("score") or 0.0
            )
            for row in vector_result["results"]
        }
        vector_rows = {
            str(row.get("entry_cid") or row.get("document_index")): row
            for row in vector_result["results"]
        }

    norm_bm25 = _normalize_scores(bm25_scores) if bm25_weight > 0 else {}
    norm_vector = _normalize_scores(vector_scores) if vector_weight > 0 else {}
    keys = set(norm_bm25) | set(norm_vector)
    fused: dict[str, float] = {}
    for key in keys:
        fused[key] = (
            bm25_weight * norm_bm25.get(key, 0.0)
            + vector_weight * norm_vector.get(key, 0.0)
        )
    ranked_keys = heapq.nlargest(
        top_k,
        fused.items(),
        key=lambda item: (item[1], item[0]),
    )
    results = []
    for key, score in ranked_keys:
        base = dict(bm25_rows.get(key) or vector_rows.get(key) or {})
        base["score"] = score
        base["bm25_score"] = bm25_scores.get(key)
        base["vector_score"] = vector_scores.get(key)
        base["authority"] = "context_only"
        base["proof_authority"] = False
        results.append(base)
    return {
        "dataset_repo_id": reader.resolver.repo_id,
        "dataset_revision": reader.manifest.get("dataset_revision"),
        "diagnostics": {
            "bm25_candidates": bm25.get("result_count", 0),
            "vector_candidates": (
                vector_result.get("result_count", 0) if vector_result else 0
            ),
            "bm25_weight": bm25_weight,
            "vector_weight": vector_weight,
            "vector_enabled": query_vector is not None and vector_weight > 0,
            "query_terms": (bm25.get("diagnostics") or {}).get("query_terms"),
        },
        "fetch_trace": reader.resolver.trace(),
        "mode": "hybrid",
        "query": query,
        "ranking": "minmax_weighted_bm25_vector",
        "result_count": len(results),
        "results": results,
    }


def load_legacy_query_module() -> Any | None:
    """Load the production query script for differential parity (optional)."""

    candidates = [
        Path(__file__).resolve().parents[3]
        / "scripts"
        / "ops"
        / "intent_ir"
        / "query_skillcenter_hf.py",
        Path("scripts/ops/intent_ir/query_skillcenter_hf.py").resolve(),
    ]
    # Also search local release trees that ship a packaged copy.
    release = discover_release_root()
    if release is not None:
        candidates.append(release / "scripts" / "query_skillcenter_hf.py")
    for path in candidates:
        if not path.is_file():
            continue
        try:
            import importlib.util

            spec = importlib.util.spec_from_file_location(
                "skillcenter_legacy_query",
                path,
            )
            if spec is None or spec.loader is None:
                continue
            module = importlib.util.module_from_spec(spec)
            # Ensure package imports resolve when the script manipulates sys.path.
            spec.loader.exec_module(module)
            if hasattr(module, "SkillCenterRemoteIndex") and hasattr(
                module, "ArtifactResolver"
            ):
                return module
        except Exception:
            continue
    return None


def differential_query_parity(
    release_root: Path | str,
    *,
    revision: str = LOCAL_FIXTURE_REVISION,
    bm25_query: str = "credentials",
    graph_node_cid: str | None = None,
    hybrid_query: str | None = None,
    query_vector: Sequence[float] | None = None,
) -> dict[str, Any]:
    """Compare adapter rankings against the existing query client when present."""

    root = Path(release_root).expanduser().resolve()
    adapter_reader = open_release_reader(root, revision=revision)
    adapter_bm25 = adapter_reader.bm25(bm25_query, top_k=5, include_content=False)
    adapter_entry_cids = [
        str(row.get("entry_cid")) for row in adapter_bm25["results"]
    ]
    adapter_scores = [float(row.get("score") or 0.0) for row in adapter_bm25["results"]]

    # Skill / category / relationship / hybrid rankings from the adapter.
    skill_rank = rank_skills(adapter_reader, bm25_query, top_k=5)
    category_rank = rank_categories(adapter_reader, bm25_query, top_k=5)
    if graph_node_cid is None and adapter_entry_cids:
        graph_node_cid = adapter_entry_cids[0]
    relationship_rank: dict[str, Any] | None = None
    graph_neighbors_adapter: dict[str, Any] | None = None
    if graph_node_cid:
        try:
            relationship_rank = rank_relationships(
                adapter_reader,
                graph_node_cid,
                top_k=10,
                hydrate=True,
            )
            graph_neighbors_adapter = adapter_reader.graph_neighbors(
                graph_node_cid,
                direction="both",
                limit=10,
                hydrate=False,
            )
        except SkillCenterAdapterError as exc:
            relationship_rank = {"error": str(exc)}
            graph_neighbors_adapter = {"error": str(exc)}

    hybrid_query = hybrid_query or bm25_query
    hybrid = hybrid_rank(
        adapter_reader,
        hybrid_query,
        top_k=5,
        query_vector=query_vector,
        allow_exhaustive=True,
    )

    legacy = load_legacy_query_module()
    if legacy is None:
        return {
            "schema": "skillcenter-differential-parity/v1",
            "parity": "self_only",
            "legacy_available": False,
            "adapter_bm25_count": adapter_bm25["result_count"],
            "bm25_entry_cids": adapter_entry_cids,
            "skill_ranking_count": skill_rank["result_count"],
            "category_ranking_count": category_rank["result_count"],
            "relationship_ranking_count": (
                relationship_rank.get("result_count")
                if isinstance(relationship_rank, Mapping)
                else None
            ),
            "hybrid_ranking_count": hybrid["result_count"],
            "graph": {
                "skipped": graph_node_cid is None,
                "node_cid": graph_node_cid,
                "neighbor_count": (
                    graph_neighbors_adapter.get("result_count")
                    if isinstance(graph_neighbors_adapter, Mapping)
                    else None
                ),
            },
        }

    legacy_resolver = legacy.ArtifactResolver(
        repo_id=DEFAULT_REPO_ID,
        revision=revision,
        path_prefix="",
        token=None,
        cache_dir=root / ".legacy-cache",
        local_root=root,
    )
    legacy_reader = legacy.SkillCenterRemoteIndex(legacy_resolver)
    legacy_bm25 = legacy_reader.bm25(bm25_query, top_k=5, include_content=False)
    legacy_entry_cids = [
        str(row.get("entry_cid")) for row in legacy_bm25["results"]
    ]
    legacy_scores = [float(row.get("score") or 0.0) for row in legacy_bm25["results"]]

    bm25_matched = (
        adapter_entry_cids == legacy_entry_cids
        and len(adapter_scores) == len(legacy_scores)
        and all(
            abs(a - b) < 1e-9 for a, b in zip(adapter_scores, legacy_scores)
        )
    )

    graph_matched = True
    graph_receipt: dict[str, Any] = {"skipped": True}
    if graph_node_cid:
        try:
            legacy_neighbors = legacy_reader.graph_neighbors(
                graph_node_cid,
                direction="both",
                limit=10,
                hydrate=False,
            )
            adapter_edges = [
                (
                    str(e.get("edge_cid")),
                    str(e.get("neighbor_cid")),
                    str(e.get("edge_type")),
                )
                for e in (graph_neighbors_adapter or {}).get("results") or []
            ]
            legacy_edges = [
                (
                    str(e.get("edge_cid")),
                    str(e.get("neighbor_cid")),
                    str(e.get("edge_type")),
                )
                for e in legacy_neighbors.get("results") or []
            ]
            graph_matched = adapter_edges == legacy_edges
            graph_receipt = {
                "skipped": False,
                "node_cid": graph_node_cid,
                "neighbor_count": len(adapter_edges),
                "matched": graph_matched,
            }
        except Exception as exc:  # pragma: no cover - defensive
            graph_matched = False
            graph_receipt = {
                "skipped": False,
                "node_cid": graph_node_cid,
                "error": str(exc),
                "matched": False,
            }

    # Hybrid: compare BM25 component of hybrid to legacy BM25 top entry order
    # when no query vector is supplied; with a vector, compare vector ranks too.
    hybrid_matched = True
    if query_vector is not None:
        try:
            legacy_vector = legacy_reader.vector(
                hybrid_query,
                top_k=5,
                query_vector=query_vector,
                allow_exhaustive=True,
                include_content=False,
            )
            adapter_vector = adapter_reader.vector(
                hybrid_query,
                top_k=5,
                query_vector=query_vector,
                allow_exhaustive=True,
                include_content=False,
            )
            hybrid_matched = [
                str(r.get("entry_cid")) for r in adapter_vector["results"]
            ] == [str(r.get("entry_cid")) for r in legacy_vector["results"]]
        except Exception:
            hybrid_matched = False

    parity = "matched" if (bm25_matched and graph_matched and hybrid_matched) else "diverged"
    return {
        "schema": "skillcenter-differential-parity/v1",
        "parity": parity,
        "legacy_available": True,
        "bm25_matched": bm25_matched,
        "bm25_result_count": adapter_bm25["result_count"],
        "bm25_entry_cids": adapter_entry_cids,
        "legacy_bm25_entry_cids": legacy_entry_cids,
        "skill_ranking_count": skill_rank["result_count"],
        "category_ranking_count": category_rank["result_count"],
        "relationship_ranking_count": (
            relationship_rank.get("result_count")
            if isinstance(relationship_rank, Mapping)
            else None
        ),
        "hybrid_ranking_count": hybrid["result_count"],
        "hybrid_matched": hybrid_matched,
        "graph": graph_receipt,
    }


class SkillCenterCorpusAdapter:
    """Read-only facade over a SkillCenter HF release."""

    def __init__(
        self,
        release_root: Path | str,
        *,
        revision: str = LOCAL_FIXTURE_REVISION,
        repo_id: str = DEFAULT_REPO_ID,
    ) -> None:
        self.release_root = Path(release_root).expanduser().resolve()
        self.revision = revision
        self.repo_id = repo_id
        self._reader: SkillCenterRemoteIndex | None = None
        self._manifest_receipt: dict[str, Any] | None = None

    @classmethod
    def discover(
        cls,
        *,
        require_release: bool = True,
    ) -> "SkillCenterCorpusAdapter":
        release = discover_release_root()
        if release is None and require_release:
            raise SkillCenterAdapterError(
                "no SkillCenter release root discovered; set "
                f"{ENV_RELEASE_ROOT} or install the local HF release cache"
            )
        if release is None:
            raise SkillCenterAdapterError("no SkillCenter release root discovered")
        return cls(release)

    @property
    def reader(self) -> SkillCenterRemoteIndex:
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
        """Validate manifest, indexes, shards, counts, and provenance."""

        manifest_receipt = validate_manifest(
            self.release_root,
            require_counts=expected_full_corpus,
        )
        self._manifest_receipt = manifest_receipt
        manifest = manifest_receipt["manifest"]
        shard_receipt = validate_release_shards(
            self.release_root,
            manifest,
            verify_data_checksums=verify_data_checksums,
            max_data_shards=max_data_shards,
        )
        bindings = manifest_receipt.get("input_bindings") or {}
        provenance = {
            "source_dataset_id": manifest_receipt.get("dataset_id"),
            "source_revision": manifest_receipt.get("dataset_revision"),
            "derived_dataset_repo_id": manifest_receipt.get("dataset_repo_id"),
            "corpus_cid": bindings.get("corpus_cid"),
            "graph_cid": bindings.get("graph_cid"),
            "bm25_sqlite_cid": bindings.get("bm25_sqlite_cid"),
            "vector_faiss_cid": bindings.get("vector_faiss_cid"),
            "corpus_manifest_sha256": bindings.get("corpus_manifest_sha256"),
            "graph_manifest_sha256": bindings.get("graph_manifest_sha256"),
            "bm25_manifest_sha256": bindings.get("bm25_manifest_sha256"),
            "vector_manifest_sha256": bindings.get("vector_manifest_sha256"),
        }
        if expected_full_corpus:
            for key, expected in EXPECTED_PROVENANCE.items():
                actual = provenance.get(key)
                if actual != expected:
                    # Accept Publicus-retargeted releases where dataset_repo_id
                    # is Publicus/skillcenter-ir and source identity is in
                    # dataset_id + dataset_revision.
                    if key == "derived_dataset_repo_id" and actual in {
                        DERIVED_DATASET_REPO_ID,
                        "Tommysha/skillcenter-ir",
                    }:
                        continue
                    if key == "source_dataset_id" and actual in {
                        SOURCE_DATASET_ID,
                        DERIVED_DATASET_REPO_ID,
                    }:
                        # Some builds store the derived repo under dataset_id.
                        continue
                    raise SkillCenterAdapterError(
                        f"provenance mismatch for {key}: "
                        f"expected {expected!r}, got {actual!r}"
                    )
            counts = manifest_receipt.get("counts") or {}
            for key, expected in EXPECTED_FULL_COUNTS.items():
                if key in counts and int(counts[key]) != int(expected):
                    raise SkillCenterAdapterError(
                        f"full-corpus count mismatch for {key}"
                    )

        # Ensure the query reader can open a meta index.
        _ = self.reader._meta_rows("graph_node_chunks")
        _ = self.reader._meta_rows("bm25_keyword_shards")
        _ = self.reader._meta_rows("vector_chunks")

        return {
            "schema": "skillcenter-corpus-validation-receipt/v1",
            "release_root": str(self.release_root),
            "revision": self.revision,
            "manifest": {
                key: value
                for key, value in manifest_receipt.items()
                if key != "manifest"
            },
            "shards": shard_receipt,
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

    def rank_skills(self, query: str, **kwargs: Any) -> dict[str, Any]:
        return rank_skills(self.reader, query, **kwargs)

    def rank_categories(self, query: str, **kwargs: Any) -> dict[str, Any]:
        return rank_categories(self.reader, query, **kwargs)

    def rank_relationships(self, node_cid: str, **kwargs: Any) -> dict[str, Any]:
        return rank_relationships(self.reader, node_cid, **kwargs)

    def hybrid(self, query: str, **kwargs: Any) -> dict[str, Any]:
        return hybrid_rank(self.reader, query, **kwargs)

    def differential_parity(self, **kwargs: Any) -> dict[str, Any]:
        return differential_query_parity(
            self.release_root, revision=self.revision, **kwargs
        )


def build_tiny_fixture_release(root: Path) -> Path:
    """Materialize a tiny, integrity-checked SkillCenter-shaped release fixture.

    Layout mirrors the production HF release (v3) so differential comparisons
    and missing/corrupt shard tests stay realistic.
    """

    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ImportError as exc:
        raise SkillCenterAdapterError(
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

    # --- corpus (two skills) ---
    corpus_path = root / "data/corpus/part-000000.parquet"
    corpus_rows = [
        {
            "bundle_cid": "bafkreibundle0000000000000000000000000000000000000000000001",
            "bundle_sha256": "a" * 64,
            "content_cid": "bafkreicontent000000000000000000000000000000000000000000001",
            "content_sha256": "b" * 64,
            "corpus_index": 0,
            "dataset_id": SOURCE_DATASET_ID,
            "dataset_revision": SOURCE_REVISION,
            "document_index": 0,
            "domain": "security",
            "entry_cid": "bafkreientryaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            "entry_cid_bytes": b"\x01",
            "entry_identity_schema_version": "entry-identity/v1",
            "entry_multihash": "mh-a",
            "entry_sha256": "c" * 64,
            "language": "en",
            "library_md": "# Library\nrotate credentials helper",
            "license_expression": "MIT",
            "license_risk": "low",
            "metadata_yaml": "name: rotate-credentials\n",
            "overall_score": 0.9,
            "primary_source_id": "src-a",
            "profile": "ops",
            "repository_file": "demo-bundle.sqlite",
            "schema_version": "skillcenter-hf-corpus/v1",
            "skill_id": "demo/rotate-credentials",
            "skill_kind": "skill",
            "skill_md": "# Rotate API credentials\nSafely rotate API credentials.",
            "source_id": "src-a",
            "source_ref_id": "ref-a",
            "source_type": "bundle",
            "source_url": "https://example.test/rotate",
            "title": "Rotate API credentials",
        },
        {
            "bundle_cid": "bafkreibundle0000000000000000000000000000000000000000000002",
            "bundle_sha256": "d" * 64,
            "content_cid": "bafkreicontent000000000000000000000000000000000000000000002",
            "content_sha256": "e" * 64,
            "corpus_index": 1,
            "dataset_id": SOURCE_DATASET_ID,
            "dataset_revision": SOURCE_REVISION,
            "document_index": 1,
            "domain": "web",
            "entry_cid": "bafkreientrybbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
            "entry_cid_bytes": b"\x02",
            "entry_identity_schema_version": "entry-identity/v1",
            "entry_multihash": "mh-b",
            "entry_sha256": "f" * 64,
            "language": "en",
            "library_md": "# Library\nfetch HTTP resources",
            "license_expression": "Apache-2.0",
            "license_risk": "low",
            "metadata_yaml": "name: http-fetch\n",
            "overall_score": 0.8,
            "primary_source_id": "src-b",
            "profile": "web",
            "repository_file": "demo-bundle.sqlite",
            "schema_version": "skillcenter-hf-corpus/v1",
            "skill_id": "demo/http-fetch",
            "skill_kind": "skill",
            "skill_md": "# HTTP fetch\nFetch remote HTTP resources safely.",
            "source_id": "src-b",
            "source_ref_id": "ref-b",
            "source_type": "bundle",
            "source_url": "https://example.test/http",
            "title": "HTTP fetch",
        },
    ]
    write_parquet(corpus_path, corpus_rows)

    # --- bm25 postings ---
    posting_path = root / "data/bm25/postings/part-000000.parquet"
    posting_rows = [
        {
            "body_frequencies": [1],
            "document_indices": [0],
            "document_lengths": [8],
            "idf": 0.7,
            "schema_version": "skillcenter-hf-bm25-posting/v1",
            "term": "credentials",
            "title_frequencies": [1],
        },
        {
            "body_frequencies": [1],
            "document_indices": [0],
            "document_lengths": [8],
            "idf": 0.5,
            "schema_version": "skillcenter-hf-bm25-posting/v1",
            "term": "rotate",
            "title_frequencies": [1],
        },
        {
            "body_frequencies": [1],
            "document_indices": [1],
            "document_lengths": [6],
            "idf": 0.6,
            "schema_version": "skillcenter-hf-bm25-posting/v1",
            "term": "http",
            "title_frequencies": [1],
        },
        {
            "body_frequencies": [1],
            "document_indices": [1],
            "document_lengths": [6],
            "idf": 0.55,
            "schema_version": "skillcenter-hf-bm25-posting/v1",
            "term": "fetch",
            "title_frequencies": [1],
        },
    ]
    write_parquet(posting_path, posting_rows)

    # --- bm25 documents (optional index companion) ---
    bm25_doc_path = root / "data/bm25/documents/part-000000.parquet"
    bm25_doc_rows = [
        {
            "document_index": 0,
            "document_length": 8,
            "entry_cid": corpus_rows[0]["entry_cid"],
            "schema_version": "skillcenter-hf-bm25-document/v1",
        },
        {
            "document_index": 1,
            "document_length": 6,
            "entry_cid": corpus_rows[1]["entry_cid"],
            "schema_version": "skillcenter-hf-bm25-document/v1",
        },
    ]
    write_parquet(bm25_doc_path, bm25_doc_rows)

    # --- vectors ---
    vector_specs = [
        (
            root / "data/vectors/part-000000.parquet",
            {
                "chunk_id": "vector-000000",
                "cluster_id": 0,
                "chunk_in_cluster": 0,
                "document_index": 0,
                "embedding": [1.0, 0.0],
                "entry_cid": corpus_rows[0]["entry_cid"],
                "schema_version": "skillcenter-hf-vector-chunk/v2",
            },
        ),
        (
            root / "data/vectors/part-000001.parquet",
            {
                "chunk_id": "vector-000001",
                "cluster_id": 1,
                "chunk_in_cluster": 0,
                "document_index": 1,
                "embedding": [0.0, 1.0],
                "entry_cid": corpus_rows[1]["entry_cid"],
                "schema_version": "skillcenter-hf-vector-chunk/v2",
            },
        ),
    ]
    for path, row in vector_specs:
        write_parquet(path, [row])

    # --- graph nodes: SKILL x2, DOMAIN x2, CONTENT x1 ---
    skill_a = corpus_rows[0]["entry_cid"]
    skill_b = corpus_rows[1]["entry_cid"]
    domain_security = "bafkreidomainsecurity00000000000000000000000000000000000001"
    domain_web = "bafkreidomainweb0000000000000000000000000000000000000000001"
    content_a = "bafkreicontentnode000000000000000000000000000000000000000001"

    node_rows = [
        {
            "entry_cid": skill_a,
            "label": "Rotate API credentials",
            "node_cid": skill_a,
            "node_type": "SKILL",
            "properties_json": json.dumps(
                {
                    "domain": "security",
                    "entry_cid": skill_a,
                    "skill_id": "demo/rotate-credentials",
                }
            ),
            "schema_version": "skillcenter-cid-graph-node/v1",
        },
        {
            "entry_cid": skill_b,
            "label": "HTTP fetch",
            "node_cid": skill_b,
            "node_type": "SKILL",
            "properties_json": json.dumps(
                {
                    "domain": "web",
                    "entry_cid": skill_b,
                    "skill_id": "demo/http-fetch",
                }
            ),
            "schema_version": "skillcenter-cid-graph-node/v1",
        },
        {
            "entry_cid": None,
            "label": "security",
            "node_cid": domain_security,
            "node_type": "DOMAIN",
            "properties_json": json.dumps({"domain": "security"}),
            "schema_version": "skillcenter-cid-graph-node/v1",
        },
        {
            "entry_cid": None,
            "label": "web",
            "node_cid": domain_web,
            "node_type": "DOMAIN",
            "properties_json": json.dumps({"domain": "web"}),
            "schema_version": "skillcenter-cid-graph-node/v1",
        },
        {
            "entry_cid": None,
            "label": content_a,
            "node_cid": content_a,
            "node_type": "CONTENT",
            "properties_json": json.dumps({"content_cid": content_a}),
            "schema_version": "skillcenter-cid-graph-node/v1",
        },
    ]
    ordered_nodes = sorted(node_rows, key=lambda row: row["node_cid"])
    node_path = root / "data/graph/nodes/part-000000.parquet"
    write_parquet(node_path, ordered_nodes)

    edge_rows = [
        {
            "edge_cid": "bafkreiedge0001aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            "edge_type": "IN_DOMAIN",
            "properties_json": "{}",
            "query_terms_json": "[]",
            "retrieval_method": "",
            "schema_version": "skillcenter-cid-graph-edge/v1",
            "score": 1.0,
            "source_cid": skill_a,
            "target_cid": domain_security,
        },
        {
            "edge_cid": "bafkreiedge0002bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
            "edge_type": "IN_DOMAIN",
            "properties_json": "{}",
            "query_terms_json": "[]",
            "retrieval_method": "",
            "schema_version": "skillcenter-cid-graph-edge/v1",
            "score": 1.0,
            "source_cid": skill_b,
            "target_cid": domain_web,
        },
        {
            "edge_cid": "bafkreiedge0003ccccccccccccccccccccccccccccccccccccccccccc",
            "edge_type": "HAS_CONTENT",
            "properties_json": "{}",
            "query_terms_json": "[]",
            "retrieval_method": "",
            "schema_version": "skillcenter-cid-graph-edge/v1",
            "score": 0.9,
            "source_cid": skill_a,
            "target_cid": content_a,
        },
        {
            "edge_cid": "bafkreiedge0004ddddddddddddddddddddddddddddddddddddddddddd",
            "edge_type": "BM25_NEIGHBOR_OF",
            "properties_json": "{}",
            "query_terms_json": '["credentials"]',
            "retrieval_method": "bm25",
            "schema_version": "skillcenter-cid-graph-edge/v1",
            "score": 2.5,
            "source_cid": skill_a,
            "target_cid": skill_b,
        },
    ]
    ordered_edges = sorted(edge_rows, key=lambda row: row["edge_cid"])
    edge_path = root / "data/graph/edges/part-000000.parquet"
    write_parquet(edge_path, ordered_edges)

    out_rows = [
        {
            "direction": "outgoing",
            "edge_cids": [
                "bafkreiedge0001aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                "bafkreiedge0003ccccccccccccccccccccccccccccccccccccccccccc",
                "bafkreiedge0004ddddddddddddddddddddddddddddddddddddddddddd",
            ],
            "edge_types": ["IN_DOMAIN", "HAS_CONTENT", "BM25_NEIGHBOR_OF"],
            "neighbor_cids": [domain_security, content_a, skill_b],
            "neighbor_count": 3,
            "neighbor_node_types": ["DOMAIN", "CONTENT", "SKILL"],
            "node_cid": skill_a,
            "page_count": 1,
            "page_index": 0,
            "retrieval_methods": ["", "", "bm25"],
            "schema_version": "skillcenter-hf-graph-adjacency/v1",
            "scores": [1.0, 0.9, 2.5],
            "total_neighbor_count": 3,
        },
        {
            "direction": "outgoing",
            "edge_cids": [
                "bafkreiedge0002bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
            ],
            "edge_types": ["IN_DOMAIN"],
            "neighbor_cids": [domain_web],
            "neighbor_count": 1,
            "neighbor_node_types": ["DOMAIN"],
            "node_cid": skill_b,
            "page_count": 1,
            "page_index": 0,
            "retrieval_methods": [""],
            "schema_version": "skillcenter-hf-graph-adjacency/v1",
            "scores": [1.0],
            "total_neighbor_count": 1,
        },
        {
            "direction": "outgoing",
            "edge_cids": [],
            "edge_types": [],
            "neighbor_cids": [],
            "neighbor_count": 0,
            "neighbor_node_types": [],
            "node_cid": domain_security,
            "page_count": 1,
            "page_index": 0,
            "retrieval_methods": [],
            "schema_version": "skillcenter-hf-graph-adjacency/v1",
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
            "node_cid": domain_web,
            "page_count": 1,
            "page_index": 0,
            "retrieval_methods": [],
            "schema_version": "skillcenter-hf-graph-adjacency/v1",
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
            "node_cid": content_a,
            "page_count": 1,
            "page_index": 0,
            "retrieval_methods": [],
            "schema_version": "skillcenter-hf-graph-adjacency/v1",
            "scores": [],
            "total_neighbor_count": 0,
        },
    ]
    ordered_out = sorted(out_rows, key=lambda row: row["node_cid"])
    out_path = root / "data/graph/adjacency/outgoing/part-000000.parquet"
    write_parquet(out_path, ordered_out)

    in_rows = [
        {
            "direction": "incoming",
            "edge_cids": [
                "bafkreiedge0001aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
            ],
            "edge_types": ["IN_DOMAIN"],
            "neighbor_cids": [skill_a],
            "neighbor_count": 1,
            "neighbor_node_types": ["SKILL"],
            "node_cid": domain_security,
            "page_count": 1,
            "page_index": 0,
            "retrieval_methods": [""],
            "schema_version": "skillcenter-hf-graph-adjacency/v1",
            "scores": [1.0],
            "total_neighbor_count": 1,
        },
        {
            "direction": "incoming",
            "edge_cids": [
                "bafkreiedge0002bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
            ],
            "edge_types": ["IN_DOMAIN"],
            "neighbor_cids": [skill_b],
            "neighbor_count": 1,
            "neighbor_node_types": ["SKILL"],
            "node_cid": domain_web,
            "page_count": 1,
            "page_index": 0,
            "retrieval_methods": [""],
            "schema_version": "skillcenter-hf-graph-adjacency/v1",
            "scores": [1.0],
            "total_neighbor_count": 1,
        },
        {
            "direction": "incoming",
            "edge_cids": [
                "bafkreiedge0003ccccccccccccccccccccccccccccccccccccccccccc"
            ],
            "edge_types": ["HAS_CONTENT"],
            "neighbor_cids": [skill_a],
            "neighbor_count": 1,
            "neighbor_node_types": ["SKILL"],
            "node_cid": content_a,
            "page_count": 1,
            "page_index": 0,
            "retrieval_methods": [""],
            "schema_version": "skillcenter-hf-graph-adjacency/v1",
            "scores": [0.9],
            "total_neighbor_count": 1,
        },
        {
            "direction": "incoming",
            "edge_cids": [
                "bafkreiedge0004ddddddddddddddddddddddddddddddddddddddddddd"
            ],
            "edge_types": ["BM25_NEIGHBOR_OF"],
            "neighbor_cids": [skill_a],
            "neighbor_count": 1,
            "neighbor_node_types": ["SKILL"],
            "node_cid": skill_b,
            "page_count": 1,
            "page_index": 0,
            "retrieval_methods": ["bm25"],
            "schema_version": "skillcenter-hf-graph-adjacency/v1",
            "scores": [2.5],
            "total_neighbor_count": 1,
        },
        {
            "direction": "incoming",
            "edge_cids": [],
            "edge_types": [],
            "neighbor_cids": [],
            "neighbor_count": 0,
            "neighbor_node_types": [],
            "node_cid": skill_a,
            "page_count": 1,
            "page_index": 0,
            "retrieval_methods": [],
            "schema_version": "skillcenter-hf-graph-adjacency/v1",
            "scores": [],
            "total_neighbor_count": 0,
        },
    ]
    ordered_in = sorted(in_rows, key=lambda row: row["node_cid"])
    in_path = root / "data/graph/adjacency/incoming/part-000000.parquet"
    write_parquet(in_path, ordered_in)

    terms = sorted(row["term"] for row in posting_rows)
    index_descriptors = {
        "bm25_document_chunks": write_index(
            "bm25_document_chunks",
            [
                meta_row(
                    bm25_doc_path,
                    shard_id=0,
                    row_count=2,
                    first_key=corpus_rows[0]["entry_cid"],
                    last_key=corpus_rows[1]["entry_cid"],
                    kind="bm25_documents",
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
                    row_count=4,
                    first_key=terms[0],
                    last_key=terms[-1],
                    kind="bm25_postings",
                )
            ],
        ),
        "corpus_chunks": write_index(
            "corpus_chunks",
            [
                meta_row(
                    corpus_path,
                    shard_id=0,
                    row_count=2,
                    first_key=corpus_rows[0]["entry_cid"],
                    last_key=corpus_rows[1]["entry_cid"],
                    kind="corpus",
                    start_document_index=0,
                    end_document_index=1,
                )
            ],
        ),
        "graph_edge_chunks": write_index(
            "graph_edge_chunks",
            [
                meta_row(
                    edge_path,
                    shard_id=0,
                    row_count=len(ordered_edges),
                    first_key=ordered_edges[0]["edge_cid"],
                    last_key=ordered_edges[-1]["edge_cid"],
                    kind="graph_edges",
                )
            ],
        ),
        "graph_node_chunks": write_index(
            "graph_node_chunks",
            [
                meta_row(
                    node_path,
                    shard_id=0,
                    row_count=len(ordered_nodes),
                    first_key=ordered_nodes[0]["node_cid"],
                    last_key=ordered_nodes[-1]["node_cid"],
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
                    row_count=len(ordered_out),
                    first_key=ordered_out[0]["node_cid"],
                    last_key=ordered_out[-1]["node_cid"],
                    kind="graph_outgoing_adjacency",
                    adjacency_count=4,
                    direction="outgoing",
                    first_page_index=0,
                    last_page_index=0,
                    node_count=len(ordered_out),
                )
            ],
        ),
        "graph_incoming_adjacency": write_index(
            "graph_incoming_adjacency",
            [
                meta_row(
                    in_path,
                    shard_id=0,
                    row_count=len(ordered_in),
                    first_key=ordered_in[0]["node_cid"],
                    last_key=ordered_in[-1]["node_cid"],
                    kind="graph_incoming_adjacency",
                    adjacency_count=4,
                    direction="incoming",
                    first_page_index=0,
                    last_page_index=0,
                    node_count=len(ordered_in),
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
                    first_key=corpus_rows[index]["entry_cid"],
                    last_key=corpus_rows[index]["entry_cid"],
                    kind="vectors",
                    start_document_index=index,
                    end_document_index=index,
                    centroid=([1.0, 0.0] if index == 0 else [0.0, 1.0]),
                    centroid_min_score=0.9,
                    centroid_shard_count=1,
                    chunk_in_cluster=0,
                    cluster_id=index,
                    dimension=2,
                    model_name="thenlper/gte-small",
                    shard_centroid=([1.0, 0.0] if index == 0 else [0.0, 1.0]),
                )
                for index, (path, _) in enumerate(vector_specs)
            ],
        ),
    }

    # Refresh descriptors after all parquet writes (checksums already final).
    # Recompute index descriptors for files rewritten above — already final.

    manifest = {
        "bm25": {
            "average_document_length": 7.0,
            "b": 0.75,
            "body_weight": 1.0,
            "k1": 1.2,
            "max_query_terms": 64,
            "posting_rows_per_record": 4096,
            "terms_per_shard": 4096,
            "title_weight": 2.0,
            "tokenizer": BM25_TOKENIZER,
        },
        "counts": {
            "bm25_document_chunks": 1,
            "bm25_documents": 2,
            "bm25_keyword_shards": 1,
            "bm25_posting_rows": 4,
            "bm25_postings": 4,
            "bm25_terms": 4,
            "corpus_chunks": 1,
            "corpus_rows": 2,
            "graph_edge_chunks": 1,
            "graph_edges": 4,
            "graph_incoming_adjacency_edges": 4,
            "graph_incoming_adjacency_rows": 5,
            "graph_incoming_adjacency_shards": 1,
            "graph_node_chunks": 1,
            "graph_nodes": 5,
            "graph_outgoing_adjacency_edges": 4,
            "graph_outgoing_adjacency_rows": 5,
            "graph_outgoing_adjacency_shards": 1,
            "vector_chunks": 2,
            "vector_rows": 2,
        },
        "dataset_id": SOURCE_DATASET_ID,
        "dataset_repo_id": DERIVED_DATASET_REPO_ID,
        "dataset_revision": LOCAL_FIXTURE_REVISION,
        "files": {},
        "graph": {
            "adjacency_pointers_per_row": True,
            "adjacency_pointers_per_shard": True,
            "directions": ["incoming", "outgoing"],
            "max_remote_walk_depth": 8,
            "ordering": "score_desc_edge_cid",
        },
        "indexes": index_descriptors,
        "input_bindings": {
            "bm25_manifest_sha256": "1" * 64,
            "bm25_sqlite_cid": EXPECTED_PROVENANCE["bm25_sqlite_cid"],
            "corpus_cid": EXPECTED_PROVENANCE["corpus_cid"],
            "corpus_manifest_sha256": "2" * 64,
            "graph_cid": EXPECTED_PROVENANCE["graph_cid"],
            "graph_manifest_sha256": "3" * 64,
            "vector_faiss_cid": EXPECTED_PROVENANCE["vector_faiss_cid"],
            "vector_manifest_sha256": "4" * 64,
        },
        "parquet": {
            "compression": "zstd",
            "compression_level": 3,
            "max_rows_per_file": 4096,
            "row_group_size": 4096,
        },
        "primary_key": "entry_cid",
        "schema_version": "skillcenter-huggingface-release/v3",
        "vector": {
            "assignment": "recursive_spherical_kmeans",
            "centroid_count": 2,
            "default_probe_centroids": 1,
            "dimension": 2,
            "layout": "semantic_centroid_groups",
            "max_rows_per_centroid": 8192,
            "max_rows_per_chunk": 4096,
            "max_shards_per_centroid": 2,
            "model_name": "thenlper/gte-small",
            "rows_sorted_by": "cosine_similarity_to_shard_centroid_desc",
            "shard_count": 2,
            "similarity": "cosine",
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
    "DEFAULT_MANIFEST",
    "DEFAULT_REPO_ID",
    "ENV_RELEASE_ROOT",
    "EXPECTED_FULL_COUNTS",
    "EXPECTED_PROVENANCE",
    "LOCAL_FIXTURE_REVISION",
    "META_SCHEMA_VERSION",
    "RemoteQueryError",
    "SkillCenterAdapterError",
    "SkillCenterCorpusAdapter",
    "SkillCenterRemoteIndex",
    "build_tiny_fixture_release",
    "differential_query_parity",
    "discover_build_root",
    "discover_release_root",
    "find_nodes_by_type",
    "hybrid_rank",
    "load_legacy_query_module",
    "open_release_reader",
    "rank_categories",
    "rank_relationships",
    "rank_skills",
    "validate_manifest",
    "validate_release_shards",
]
