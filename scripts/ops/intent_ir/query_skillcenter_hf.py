#!/usr/bin/env python3
"""Query a sharded SkillCenter Hugging Face release without full download.

Examples:

  python query_skillcenter_hf.py bm25 "rotate API credentials" --top-k 5
  python query_skillcenter_hf.py vector "rotate API credentials" \
      --candidate-centroids 4 --device cuda --top-k 5
  python query_skillcenter_hf.py graph neighbors <node-cid> \
      --direction both --limit 25
  python query_skillcenter_hf.py graph walk <node-cid> \
      --max-depth 2 --max-nodes 100 --max-shards 32
  python query_skillcenter_hf.py graph walk <node-cid> \
      --strategy semantic-beam --query "rotate credentials safely" \
      --direction adaptive --candidate-centroids 4 --max-vector-shards 8

The client downloads only the release manifest, compact meta-indexes, relevant
BM25 posting or vector shards, and corpus shards containing final results.
"""

from __future__ import annotations

import argparse
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

# Make direct execution from a source checkout resolve the checkout package
# before any older installed copy.  Packaged Hub scripts use the sibling
# fallback below instead.
_source_root = Path(__file__).resolve().parents[3]
_source_module = (
    _source_root
    / "ipfs_datasets_py"
    / "knowledge_graphs"
    / "query"
    / "semantic_traversal.py"
)
if _source_module.is_file():
    sys.path.insert(0, str(_source_root))

try:
    from ipfs_datasets_py.knowledge_graphs.query.semantic_traversal import (
        EmbeddingGuidedTraversal,
        SemanticTraversalConfig,
        TraversalEdge,
    )
except ImportError:
    # Standalone copy included beside this script in a Hub release.
    from semantic_traversal import (  # type: ignore
        EmbeddingGuidedTraversal,
        SemanticTraversalConfig,
        TraversalEdge,
    )


DEFAULT_REPO_ID = "Publicus/skillcenter-ir"
DEFAULT_MANIFEST = "manifest.json"
DEFAULT_CACHE_DIR = Path(
    "~/.cache/ipfs_datasets_py/skillcenter-hf-query"
).expanduser()
TOKEN_RE = re.compile(r"[A-Za-z0-9_]+")
MAX_QUERY_TERMS = 64
MAX_TOP_K = 1000
MAX_GRAPH_DEPTH = 8
MAX_GRAPH_NODES = 10_000
MAX_GRAPH_EDGES = 100_000
MAX_GRAPH_SHARDS = 1_024
MAX_VECTOR_SHARDS = 128
SUPPORTED_RELEASE_SCHEMAS = {
    "skillcenter-huggingface-release/v1",
    "skillcenter-huggingface-release/v2",
    "skillcenter-huggingface-release/v3",
}


class RemoteQueryError(RuntimeError):
    """Raised when a remote release or query is malformed."""


class _GraphShardBudgetReached(RuntimeError):
    """Internal signal used to stop a bounded walk cleanly."""


class ArtifactResolver:
    """Resolve only explicitly requested files from local or Hub storage."""

    def __init__(
        self,
        *,
        repo_id: str,
        revision: str,
        path_prefix: str,
        token: str | None,
        cache_dir: Path,
        local_root: Path | None,
    ) -> None:
        self.repo_id = repo_id
        self.revision = revision
        self.path_prefix = path_prefix.strip("/")
        self.token = token
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


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Query SkillCenter BM25/vector Parquet shards on Hugging Face "
            "without downloading the complete dataset"
        )
    )
    parser.add_argument("--repo-id", default=DEFAULT_REPO_ID)
    parser.add_argument("--revision", default="main")
    parser.add_argument("--path-prefix", default="")
    parser.add_argument("--manifest", default=DEFAULT_MANIFEST)
    parser.add_argument("--token", default=None)
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE_DIR)
    parser.add_argument(
        "--local-root",
        type=Path,
        default=None,
        help="Query a local release instead of Hugging Face (testing/offline).",
    )
    parser.add_argument(
        "--no-content",
        action="store_true",
        help="Return metadata without skill_md/library_md/metadata_yaml.",
    )
    subparsers = parser.add_subparsers(dest="mode", required=True)
    bm25 = subparsers.add_parser("bm25", help="BM25 keyword retrieval")
    bm25.add_argument("query")
    bm25.add_argument("--top-k", type=int, default=10)
    vector = subparsers.add_parser(
        "vector",
        help="Centroid-routed vector retrieval",
    )
    vector.add_argument("query")
    vector.add_argument("--top-k", type=int, default=10)
    vector.add_argument(
        "--candidate-chunks",
        type=int,
        default=None,
        help=(
            "Legacy alias for the number of routing cells to probe. Prefer "
            "--candidate-centroids with v2 releases."
        ),
    )
    vector.add_argument(
        "--candidate-centroids",
        type=int,
        default=None,
        help=(
            "Semantic centroids to probe; each fetches one or two vector "
            "shards. The release default is normally 4."
        ),
    )
    vector.add_argument("--device", choices=["auto", "cpu", "cuda"], default="auto")
    vector.add_argument("--model", default=None)
    vector.add_argument(
        "--query-vector-json",
        default=None,
        help="JSON array or path; skips local model inference.",
    )
    vector.add_argument("--allow-exhaustive", action="store_true")
    graph = subparsers.add_parser(
        "graph",
        help="Bounded CID-based knowledge-graph queries and walks",
    )
    graph_modes = graph.add_subparsers(
        dest="graph_mode",
        required=True,
    )
    graph_node = graph_modes.add_parser(
        "node",
        help="Resolve one graph node by CID",
    )
    graph_node.add_argument("node_cid")
    graph_neighbors = graph_modes.add_parser(
        "neighbors",
        help="Fetch a bounded incoming/outgoing adjacency page",
    )
    graph_neighbors.add_argument("node_cid")
    graph_neighbors.add_argument(
        "--direction",
        choices=["incoming", "outgoing", "both"],
        default="both",
    )
    graph_neighbors.add_argument("--limit", type=int, default=50)
    graph_neighbors.add_argument("--offset", type=int, default=0)
    graph_neighbors.add_argument(
        "--edge-type",
        action="append",
        default=[],
        dest="edge_types",
    )
    graph_neighbors.add_argument("--hydrate", action="store_true")
    graph_neighbors.add_argument("--max-shards", type=int, default=64)
    graph_walk = graph_modes.add_parser(
        "walk",
        help="BFS or embedding-guided graph walk with hard resource budgets",
    )
    graph_walk.add_argument("start_node_cid")
    graph_walk.add_argument(
        "--strategy",
        choices=["bfs", "semantic-beam"],
        default="bfs",
    )
    graph_walk.add_argument(
        "--direction",
        choices=["incoming", "outgoing", "both", "adaptive"],
        default="outgoing",
    )
    graph_walk.add_argument("--max-depth", type=int, default=2)
    graph_walk.add_argument("--max-nodes", type=int, default=100)
    graph_walk.add_argument("--max-edges", type=int, default=500)
    graph_walk.add_argument("--per-node-limit", type=int, default=16)
    graph_walk.add_argument("--max-shards", type=int, default=64)
    graph_walk.add_argument(
        "--edge-type",
        action="append",
        default=[],
        dest="edge_types",
    )
    graph_walk.add_argument("--hydrate", action="store_true")
    graph_walk.add_argument(
        "--query",
        default=None,
        help="Semantic destination text; required unless a vector is supplied.",
    )
    graph_walk.add_argument(
        "--query-vector-json",
        default=None,
        help="JSON array or path; skips local model inference.",
    )
    graph_walk.add_argument(
        "--candidate-centroids",
        type=int,
        default=None,
        help="Query-nearest vector centroids to make available to traversal.",
    )
    graph_walk.add_argument("--max-vector-shards", type=int, default=8)
    graph_walk.add_argument("--beam-width", type=int, default=16)
    graph_walk.add_argument(
        "--device",
        choices=["auto", "cpu", "cuda"],
        default="auto",
    )
    graph_walk.add_argument("--model", default=None)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    token = args.token or os.environ.get("HF_TOKEN")
    resolver = ArtifactResolver(
        repo_id=args.repo_id,
        revision=args.revision,
        path_prefix=args.path_prefix,
        token=token,
        cache_dir=args.cache_dir.expanduser().resolve(),
        local_root=args.local_root,
    )
    index = SkillCenterRemoteIndex(
        resolver,
        manifest_path=args.manifest,
    )
    if args.mode == "bm25":
        result = index.bm25(
            args.query,
            top_k=args.top_k,
            include_content=not args.no_content,
        )
    elif args.mode == "vector":
        vector_config = dict(index.manifest["vector"])
        model_name = args.model or str(vector_config["model_name"])
        if args.query_vector_json:
            query_vector = _read_query_vector(args.query_vector_json)
            embedding_device = "provided"
            embedding_fallback = ""
        else:
            (
                query_vector,
                embedding_device,
                embedding_fallback,
            ) = _embed_query(
                args.query,
                model_name=model_name,
                device=args.device,
            )
        result = index.vector(
            args.query,
            top_k=args.top_k,
            query_vector=query_vector,
            candidate_chunks=args.candidate_chunks,
            candidate_centroids=args.candidate_centroids,
            include_content=not args.no_content,
            allow_exhaustive=args.allow_exhaustive,
        )
        result["diagnostics"]["query_embedding_device"] = embedding_device
        if embedding_fallback:
            result["diagnostics"]["query_embedding_fallback"] = (
                embedding_fallback
            )
    elif args.graph_mode == "node":
        result = index.graph_node(args.node_cid)
    elif args.graph_mode == "neighbors":
        result = index.graph_neighbors(
            args.node_cid,
            direction=args.direction,
            limit=args.limit,
            offset=args.offset,
            edge_types=args.edge_types,
            hydrate=args.hydrate,
            max_shards=args.max_shards,
        )
    else:
        if args.strategy == "bfs":
            if args.direction == "adaptive":
                raise RemoteQueryError(
                    "adaptive direction requires --strategy semantic-beam"
                )
            result = index.graph_walk(
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
        else:
            vector_config = dict(index.manifest["vector"])
            model_name = args.model or str(vector_config["model_name"])
            if args.query_vector_json:
                query_vector = _read_query_vector(args.query_vector_json)
                embedding_device = "provided"
                embedding_fallback = ""
            else:
                if not str(args.query or "").strip():
                    raise RemoteQueryError(
                        "--query is required for semantic traversal unless "
                        "--query-vector-json is supplied"
                    )
                (
                    query_vector,
                    embedding_device,
                    embedding_fallback,
                ) = _embed_query(
                    args.query,
                    model_name=model_name,
                    device=args.device,
                )
            candidate_centroids = (
                args.candidate_centroids
                if args.candidate_centroids is not None
                else int(
                    vector_config.get("default_probe_centroids", 4)
                )
            )
            result = index.graph_semantic_walk(
                args.start_node_cid,
                query=str(args.query or ""),
                query_vector=query_vector,
                direction=args.direction,
                max_depth=args.max_depth,
                max_nodes=args.max_nodes,
                max_edges=args.max_edges,
                per_node_limit=args.per_node_limit,
                max_shards=args.max_shards,
                candidate_centroids=candidate_centroids,
                max_vector_shards=args.max_vector_shards,
                beam_width=args.beam_width,
                edge_types=args.edge_types,
                hydrate=args.hydrate,
            )
            result["diagnostics"]["query_embedding_device"] = (
                embedding_device
            )
            if embedding_fallback:
                result["diagnostics"]["query_embedding_fallback"] = (
                    embedding_fallback
                )
    json.dump(result, sys.stdout, indent=2, sort_keys=True, ensure_ascii=False)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
