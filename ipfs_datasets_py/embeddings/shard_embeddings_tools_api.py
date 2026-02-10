"""Embedding shard tool APIs (package-level).

Reusable core logic behind MCP-facing sharding tools.
MCP wrappers should stay thin delegates that validate/dispatch/format.

This provides lightweight in-memory sharding for embedding lists plus optional
file-backed sharding/merging via the existing advanced implementation.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Union

from ipfs_datasets_py.mcp_server.tools.embedding_tools.embedding_tools import shard_embeddings as _simple_shard_embeddings
from ipfs_datasets_py.mcp_server.tools.embedding_tools.shard_embeddings import (
    merge_embedding_shards as _merge_embedding_shards,
    shard_embeddings_by_cluster as _shard_embeddings_by_cluster,
    shard_embeddings_by_dimension as _shard_embeddings_by_dimension,
)


async def shard_embeddings_from_parameters(
    *,
    embeddings: Optional[List[Any]] = None,
    shard_count: int = 4,
    strategy: str = "balanced",
    embeddings_data: Optional[Union[str, List[Dict[str, Any]]]] = None,
    output_directory: Optional[str] = None,
    shard_size: int = 1000,
    dimension_chunks: Optional[int] = None,
    num_clusters: int = 10,
    clustering_method: str = "kmeans",
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Shard embeddings.

    Two modes:
    - In-memory mode (default): provide `embeddings` and get shards back in response.
    - File-backed mode: provide `embeddings_data` + `output_directory` and get a manifest.
    """

    if embeddings_data is not None or output_directory is not None:
        if embeddings_data is None or output_directory is None:
            raise ValueError("embeddings_data and output_directory are required for file-backed sharding")

        if strategy in ("dimension", "by_dimension"):
            return await _shard_embeddings_by_dimension(
                embeddings_data=embeddings_data,
                output_directory=output_directory,
                shard_size=shard_size,
                dimension_chunks=dimension_chunks,
                metadata=metadata,
            )

        if strategy in ("cluster", "by_cluster"):
            return await _shard_embeddings_by_cluster(
                embeddings_data=embeddings_data,
                output_directory=output_directory,
                num_clusters=num_clusters,
                clustering_method=clustering_method,
                shard_size=shard_size,
            )

        raise ValueError("Unsupported file-backed sharding strategy")

    if embeddings is None:
        raise ValueError("embeddings is required for in-memory sharding")

    return await _simple_shard_embeddings(embeddings=embeddings, shard_count=shard_count, strategy=strategy)


async def merge_shards_from_parameters(
    *,
    manifest_file: str,
    output_file: str,
    merge_strategy: str = "sequential",
    **kwargs: Any,
) -> Dict[str, Any]:
    return await _merge_embedding_shards(
        manifest_file=manifest_file,
        output_file=output_file,
        merge_strategy=merge_strategy,
        **kwargs,
    )


async def shard_info_from_parameters(
    *,
    shards: Optional[List[Dict[str, Any]]] = None,
    manifest: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Return quick info for shard structures.

    Accepts either a `shards` list (in-memory mode) or a parsed `manifest` dict.
    """

    if manifest is not None:
        meta = manifest.get("metadata", {}) if isinstance(manifest, dict) else {}
        shards_list = manifest.get("shards", []) if isinstance(manifest, dict) else []
        return {
            "mode": "manifest",
            "total_shards": len(shards_list) if isinstance(shards_list, list) else 0,
            "total_embeddings": meta.get("total_embeddings"),
            "shard_size": meta.get("shard_size"),
            "embedding_dimension": meta.get("embedding_dimension"),
        }

    shards = shards or []
    counts = []
    for shard in shards:
        if isinstance(shard, dict) and "embeddings" in shard and isinstance(shard["embeddings"], list):
            counts.append(len(shard["embeddings"]))
        elif isinstance(shard, list):
            counts.append(len(shard))

    return {
        "mode": "in_memory",
        "total_shards": len(shards),
        "shard_counts": counts,
        "total_embeddings": sum(counts),
    }
