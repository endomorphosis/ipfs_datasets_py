"""
Canonical embedding shard engine.

Provides shard_embeddings_by_dimension, shard_embeddings_by_cluster,
and merge_embedding_shards for large-scale vector processing.

MCP tool wrapper: ipfs_datasets_py.mcp_server.tools.embedding_tools.shard_embeddings

After DuckDB promotion (DQK-064), normal runtime never writes shard JSON or
mutable sharding/clustering manifests; shard metadata is projected into the
DuckDB vector catalog. Explicit import/export permits remain the only path
for legacy JSON I/O.
"""

from typing import List, Dict, Any, Optional, Union
import os
import json
import logging
import hashlib
import math
import time
from pathlib import Path

logger = logging.getLogger(__name__)


def _legacy_shard_json_io_allowed() -> bool:
    """Return False after DuckDB promotion when no import/export permit is held."""
    try:
        from ipfs_datasets_py.vector_stores.management_engine import (
            duckdb_only_after_promotion,
            legacy_metadata_io_allowed,
        )
        if duckdb_only_after_promotion():
            return False
        return legacy_metadata_io_allowed()
    except Exception:
        return True


def _guarded_json_write(path: Path, payload: Any) -> bool:
    """Write JSON only when legacy I/O is allowed; return True if written."""
    try:
        from ipfs_datasets_py.vector_stores.management_engine import (
            ImplicitLegacyMetadataError,
            assert_legacy_metadata_path_allowed,
        )
        assert_legacy_metadata_path_allowed(path, operation="write")
    except ImplicitLegacyMetadataError:
        logger.debug("Blocked legacy shard/manifest JSON write: %s", path)
        return False
    except Exception:
        if not _legacy_shard_json_io_allowed():
            return False
    with open(path, "w") as f:
        json.dump(payload, f, indent=2)
    return True


async def shard_embeddings_by_dimension(
    embeddings_data: Union[str, List[Dict[str, Any]]],
    output_directory: str,
    shard_size: int = 1000,
    dimension_chunks: Optional[int] = None,
    metadata: Optional[Dict[str, Any]] = None,
    **kwargs
) -> Dict[str, Any]:
    """
    Shard embeddings by splitting high-dimensional vectors into smaller chunks.

    Args:
        embeddings_data: Path to embeddings file or list of embedding dicts
        output_directory: Directory to save sharded embeddings
        shard_size: Maximum number of embeddings per shard
        dimension_chunks: Number of dimensions per chunk (for dimension-based sharding)
        metadata: Additional metadata to include
        **kwargs: Additional parameters

    Returns:
        Dict containing sharding results and metadata
    """
    try:
        output_path = Path(output_directory)
        output_path.mkdir(parents=True, exist_ok=True)

        if isinstance(embeddings_data, str):
            if not os.path.exists(embeddings_data):
                raise FileNotFoundError(f"Embeddings file not found: {embeddings_data}")
            with open(embeddings_data, 'r') as f:
                data = json.load(f)
            if isinstance(data, dict) and 'embeddings' in data:
                embeddings = data['embeddings']
            elif isinstance(data, list):
                embeddings = data
            else:
                raise ValueError("Invalid embeddings data format")
        else:
            embeddings = embeddings_data

        if not embeddings:
            raise ValueError("No embeddings data provided")

        sample_embedding = embeddings[0]
        if not isinstance(sample_embedding, dict) or 'embedding' not in sample_embedding:
            raise ValueError("Embeddings must contain 'embedding' field")

        embedding_dim = len(sample_embedding['embedding'])
        total_embeddings = len(embeddings)
        total_shards = math.ceil(total_embeddings / shard_size)

        shards_info = []
        shard_metadata = {
            "total_embeddings": total_embeddings,
            "total_shards": total_shards,
            "shard_size": shard_size,
            "embedding_dimension": embedding_dim,
            "dimension_chunks": dimension_chunks,
            "original_metadata": metadata or {},
            "sharding_strategy": "by_count",
        }

        for shard_idx in range(total_shards):
            start_idx = shard_idx * shard_size
            end_idx = min(start_idx + shard_size, total_embeddings)
            shard_embeddings = embeddings[start_idx:end_idx]

            if dimension_chunks and dimension_chunks < embedding_dim:
                dimension_shards = []
                chunks_per_dim = math.ceil(embedding_dim / dimension_chunks)

                for dim_chunk_idx in range(chunks_per_dim):
                    dim_start = dim_chunk_idx * dimension_chunks
                    dim_end = min(dim_start + dimension_chunks, embedding_dim)

                    chunked_embeddings = []
                    for embedding_item in shard_embeddings:
                        chunked_item = embedding_item.copy()
                        chunked_item['embedding'] = embedding_item['embedding'][dim_start:dim_end]
                        chunked_item['dimension_range'] = [dim_start, dim_end]
                        chunked_embeddings.append(chunked_item)

                    dim_shard_filename = f"shard_{shard_idx:04d}_dim_{dim_chunk_idx:04d}.json"
                    dim_shard_path = output_path / dim_shard_filename
                    dim_payload = {
                        "embeddings": chunked_embeddings,
                        "shard_info": {
                            "shard_index": shard_idx,
                            "dimension_chunk_index": dim_chunk_idx,
                            "embedding_count": len(chunked_embeddings),
                            "dimension_range": [dim_start, dim_end],
                            "dimension_size": dim_end - dim_start,
                        },
                        "metadata": shard_metadata,
                    }
                    written = _guarded_json_write(dim_shard_path, dim_payload)

                    dimension_shards.append({
                        "filename": dim_shard_filename,
                        "path": str(dim_shard_path) if written else None,
                        "dimension_range": [dim_start, dim_end],
                        "embedding_count": len(chunked_embeddings),
                        "json_written": written,
                    })

                shards_info.append({
                    "shard_index": shard_idx,
                    "embedding_range": [start_idx, end_idx],
                    "embedding_count": len(shard_embeddings),
                    "dimension_shards": dimension_shards,
                    "type": "dimension_chunked",
                })
            else:
                shard_filename = f"shard_{shard_idx:04d}.json"
                shard_path = output_path / shard_filename
                shard_payload = {
                    "embeddings": shard_embeddings,
                    "shard_info": {
                        "shard_index": shard_idx,
                        "embedding_range": [start_idx, end_idx],
                        "embedding_count": len(shard_embeddings),
                        "full_dimension": embedding_dim,
                    },
                    "metadata": shard_metadata,
                }
                written = _guarded_json_write(shard_path, shard_payload)

                shards_info.append({
                    "shard_index": shard_idx,
                    "filename": shard_filename,
                    "path": str(shard_path) if written else None,
                    "embedding_range": [start_idx, end_idx],
                    "embedding_count": len(shard_embeddings),
                    "type": "standard",
                    "json_written": written,
                })

        manifest = {
            "metadata": shard_metadata,
            "shards": shards_info,
            "created_at": str(time.time()),
            "output_directory": str(output_path),
        }
        manifest_path = output_path / "sharding_manifest.json"
        manifest_written = _guarded_json_write(manifest_path, manifest)

        result = {
            "status": "success",
            "output_directory": str(output_path),
            "total_shards": len(shards_info),
            "total_embeddings": total_embeddings,
            "shards": shards_info,
            "manifest_file": str(manifest_path) if manifest_written else None,
            "manifest_json_written": manifest_written,
            "metadata": shard_metadata,
        }

        # Dual/shadow shard manifests into DuckDB vector catalog (DQK-062/063/064).
        try:
            from ipfs_datasets_py.vector_stores.management_engine import (
                get_vector_authority_catalog,
                get_vector_shadow_catalog,
                safe_dual_create,
                safe_shadow_create,
                duckdb_metadata_is_authority,
            )
            logical = Path(output_directory).name or "embedding-shards"
            mapping = {
                f"shard_{info.get('shard_index', i)}": i
                for i, info in enumerate(shards_info)
            }
            create_fn = (
                safe_dual_create
                if duckdb_metadata_is_authority()
                else safe_shadow_create
            )
            create_kwargs = dict(
                logical_name=logical,
                backend="shard_embeddings",
                dimension=int(embedding_dim),
                dtype="float32",
                mapping=mapping,
                metadata_json={
                    "producer": "shard_embeddings_engine",
                    "manifest_file": (
                        str(manifest_path) if manifest_written else None
                    ),
                    "manifest": manifest,
                    "bytes_location": "immutable_segment",
                    "publication_approved": True,
                },
                shard_manifest={
                    "shard_index": 0,
                    "vector_count": total_embeddings,
                    "shard_id": f"shard_manifest_{logical}",
                    "total_shards": len(shards_info),
                },
                model_provider="embeddings",
                model_name="shard-embeddings",
                chunking_identity="chunk:shard@1",
                normalization_identity="norm:none@1",
                source_revision="src-shard-1",
            )
            try:
                shadow = create_fn(**create_kwargs, bytes_location="immutable_segment")
            except TypeError:
                shadow = create_fn(**create_kwargs)
            if shadow is not None:
                result["shadow"] = shadow.to_dict()
                result["authority"] = shadow.authority
                catalog = (
                    get_vector_authority_catalog() or get_vector_shadow_catalog()
                )
                if catalog is not None and catalog.enabled:
                    for info in shards_info:
                        catalog.shadow_shard_manifest(
                            logical_name=logical,
                            backend="shard_embeddings",
                            shard_manifest={
                                "shard_index": int(info.get("shard_index", 0)),
                                "vector_count": int(
                                    info.get("embedding_count", 0)
                                ),
                                "path": info.get("path") or info.get("filename"),
                                "type": info.get("type"),
                            },
                        )
        except Exception as shadow_exc:  # noqa: BLE001
            logger.warning(
                "Shard embeddings shadow quarantined (legacy ok): %s",
                shadow_exc,
            )

        return result

    except Exception as e:
        logger.error(f"Embedding sharding failed: {e}")
        return {
            "status": "error",
            "error": str(e),
            "output_directory": output_directory,
        }


async def shard_embeddings_by_cluster(
    embeddings_data: Union[str, List[Dict[str, Any]]],
    output_directory: str,
    num_clusters: int = 10,
    clustering_method: str = "kmeans",
    shard_size: int = 1000,
    **kwargs
) -> Dict[str, Any]:
    """
    Shard embeddings by clustering similar vectors together.

    Args:
        embeddings_data: Path to embeddings file or list of embedding dicts
        output_directory: Directory to save sharded embeddings
        num_clusters: Number of clusters to create
        clustering_method: Clustering algorithm to use (kmeans, hierarchical)
        shard_size: Maximum number of embeddings per shard within each cluster
        **kwargs: Additional parameters

    Returns:
        Dict containing cluster-based sharding results
    """
    try:
        output_path = Path(output_directory)
        output_path.mkdir(parents=True, exist_ok=True)

        if isinstance(embeddings_data, str):
            if not os.path.exists(embeddings_data):
                raise FileNotFoundError(f"Embeddings file not found: {embeddings_data}")
            with open(embeddings_data, 'r') as f:
                data = json.load(f)
            if isinstance(data, dict) and 'embeddings' in data:
                embeddings = data['embeddings']
            elif isinstance(data, list):
                embeddings = data
            else:
                raise ValueError("Invalid embeddings data format")
        else:
            embeddings = embeddings_data

        total_embeddings = len(embeddings)

        import random
        random.seed(42)

        clusters: Dict[int, list] = {i: [] for i in range(num_clusters)}
        for i, embedding in enumerate(embeddings):
            cluster_id = random.randint(0, num_clusters - 1)
            clusters[cluster_id].append((i, embedding))

        cluster_shards = []

        for cluster_id, cluster_embeddings in clusters.items():
            if not cluster_embeddings:
                continue

            cluster_shard_count = math.ceil(len(cluster_embeddings) / shard_size)

            for shard_idx in range(cluster_shard_count):
                start_idx = shard_idx * shard_size
                end_idx = min(start_idx + shard_size, len(cluster_embeddings))

                shard_embeddings = [emb[1] for emb in cluster_embeddings[start_idx:end_idx]]
                original_indices = [emb[0] for emb in cluster_embeddings[start_idx:end_idx]]

                shard_filename = f"cluster_{cluster_id:04d}_shard_{shard_idx:04d}.json"
                shard_path = output_path / shard_filename
                payload = {
                    "embeddings": shard_embeddings,
                    "shard_info": {
                        "cluster_id": cluster_id,
                        "shard_index": shard_idx,
                        "embedding_count": len(shard_embeddings),
                        "original_indices": original_indices,
                        "clustering_method": clustering_method,
                    },
                }
                written = _guarded_json_write(shard_path, payload)

                cluster_shards.append({
                    "cluster_id": cluster_id,
                    "shard_index": shard_idx,
                    "filename": shard_filename,
                    "path": str(shard_path) if written else None,
                    "embedding_count": len(shard_embeddings),
                    "json_written": written,
                })

        manifest = {
            "metadata": {
                "total_embeddings": total_embeddings,
                "num_clusters": num_clusters,
                "clustering_method": clustering_method,
                "total_shards": len(cluster_shards),
                "shard_size": shard_size,
            },
            "cluster_shards": cluster_shards,
            "output_directory": str(output_path),
        }
        manifest_path = output_path / "clustering_manifest.json"
        manifest_written = _guarded_json_write(manifest_path, manifest)

        return {
            "status": "success",
            "output_directory": str(output_path),
            "total_clusters": num_clusters,
            "total_shards": len(cluster_shards),
            "cluster_shards": cluster_shards,
            "manifest_file": str(manifest_path) if manifest_written else None,
            "manifest_json_written": manifest_written,
            "note": "Clustering simulation - full implementation requires ML libraries",
        }

    except Exception as e:
        logger.error(f"Cluster-based sharding failed: {e}")
        return {
            "status": "error",
            "error": str(e),
            "output_directory": output_directory,
        }


async def merge_embedding_shards(
    manifest_file: str,
    output_file: str,
    merge_strategy: str = "sequential",
    **kwargs
) -> Dict[str, Any]:
    """
    Merge previously sharded embeddings back into a single file.

    Args:
        manifest_file: Path to the sharding manifest file
        output_file: Path for the merged output file
        merge_strategy: Strategy for merging (sequential, clustered)
        **kwargs: Additional parameters

    Returns:
        Dict containing merge results
    """
    try:
        if not os.path.exists(manifest_file):
            raise FileNotFoundError(f"Manifest file not found: {manifest_file}")

        with open(manifest_file, 'r') as f:
            manifest = json.load(f)

        output_path = Path(output_file)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        merged_embeddings: list = []

        if merge_strategy == "sequential":
            shards = manifest.get('shards', manifest.get('cluster_shards', []))
            for shard_info in sorted(shards, key=lambda x: x.get('shard_index', 0)):
                shard_path = shard_info['path']
                if os.path.exists(shard_path):
                    with open(shard_path, 'r') as f:
                        shard_data = json.load(f)
                    merged_embeddings.extend(shard_data['embeddings'])

        elif merge_strategy == "clustered":
            cluster_shards = manifest.get('cluster_shards', [])
            clusters: Dict[int, list] = {}
            for shard_info in cluster_shards:
                cid = shard_info['cluster_id']
                clusters.setdefault(cid, []).append(shard_info)

            for cid in sorted(clusters.keys()):
                for shard_info in sorted(clusters[cid], key=lambda x: x['shard_index']):
                    shard_path = shard_info['path']
                    if os.path.exists(shard_path):
                        with open(shard_path, 'r') as f:
                            shard_data = json.load(f)
                        merged_embeddings.extend(shard_data['embeddings'])

        merged_data = {
            "embeddings": merged_embeddings,
            "metadata": {
                "total_embeddings": len(merged_embeddings),
                "merge_strategy": merge_strategy,
                "original_manifest": manifest_file,
                "merged_from_shards": len(
                    manifest.get('shards', manifest.get('cluster_shards', []))
                ),
            },
        }

        with open(output_path, 'w') as f:
            json.dump(merged_data, f, indent=2)

        return {
            "status": "success",
            "output_file": str(output_path),
            "total_embeddings": len(merged_embeddings),
            "merge_strategy": merge_strategy,
            "shards_merged": len(manifest.get('shards', manifest.get('cluster_shards', []))),
        }

    except Exception as e:
        logger.error(f"Shard merging failed: {e}")
        return {
            "status": "error",
            "error": str(e),
            "manifest_file": manifest_file,
            "output_file": output_file,
        }


__all__ = [
    "shard_embeddings_by_dimension",
    "shard_embeddings_by_cluster",
    "merge_embedding_shards",
]
