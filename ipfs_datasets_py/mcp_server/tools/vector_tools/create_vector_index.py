# ipfs_datasets_py/mcp_server/tools/vector_tools/create_vector_index.py
"""
MCP tool for creating vector indexes.

This tool handles creating vector indexes for similarity search
using the VectorStore from vector_tools.
"""
import anyio
import uuid
from typing import Dict, Any, Optional, Union, List

import numpy as np

import logging

logger = logging.getLogger(__name__)
from ipfs_datasets_py.vector_tools import VectorStore, create_vector_store


# Global manager instance to maintain state between calls
from .shared_state import _get_global_manager


async def create_vector_index(
    vectors: List[List[float]],
    dimension: Optional[int] = None,
    metric: str = "cosine",
    metadata: Optional[List[Dict[str, Any]]] = None,
    index_id: Optional[str] = None,
    index_name: Optional[str] = None
) -> Dict[str, Any]:
    """
    Create a vector index for similarity search.

    Args:
        vectors: List of vectors to index
        dimension: Dimension of the vectors (inferred if not provided)
        metric: Distance metric to use ('cosine', 'l2', 'ip', etc.)
        metadata: Optional metadata for each vector
        index_id: Optional ID for the index (generated if not provided)
        index_name: Optional name for the index

    Returns:
        Dict containing information about the created index
    """
    try:
        logger.info(f"Creating vector index with {len(vectors)} vectors")
        # Get the global manager (synchronous internal helper)
        manager = _get_global_manager()

        # Infer dimension if not provided
        if dimension is None and vectors:
            dimension = len(vectors[0])

        # Generate index ID if not provided
        if index_id is None:
            index_id = f"index_{uuid.uuid4().hex[:8]}"

        # Create a vector index using the manager
        index = manager.create_index(index_id, dimension=dimension, metric=metric)
        if index_name:
            index.index_name = index_name

        # Convert vectors to numpy arrays and add to index
        np_vectors = np.array(vectors)
        
        # Handle metadata: if provided but doesn't match vector count, adjust it
        if metadata is not None:
            if isinstance(metadata, dict):
                # If single dict provided, replicate for all vectors
                metadata = [metadata.copy() for _ in range(len(vectors))]
            elif isinstance(metadata, list) and len(metadata) != len(vectors):
                if len(metadata) == 1:
                    # If single item in list, replicate for all vectors
                    metadata = metadata * len(vectors)
                else:
                    # If mismatch, create default metadata for all vectors
                    logger.warning(f"Metadata count ({len(metadata)}) doesn't match vector count ({len(vectors)}). Using default metadata.")
                    metadata = [{"vector_index": i} for i in range(len(vectors))]
        
        vector_ids = index.add_vectors(np_vectors, metadata=metadata)

        # Return information about the index
        return {
            "status": "success",
            "index_id": index.index_id,
            "num_vectors": len(vectors),
            "dimension": dimension,
            "metric": metric,
            "vector_ids": vector_ids
        }
    except Exception as e:
        logger.error(f"Error creating vector index: {e}")
        return {
            "status": "error",
            "message": str(e)
        }
