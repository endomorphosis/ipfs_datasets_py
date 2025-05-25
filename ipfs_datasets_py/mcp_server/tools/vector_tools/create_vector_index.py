# ipfs_datasets_py/mcp_server/tools/vector_tools/create_vector_index.py
"""
MCP tool for creating vector indexes.

This tool handles creating vector indexes for similarity search.
"""
import asyncio
from typing import Dict, Any, Optional, Union, List

import numpy as np

from ipfs_datasets_py.mcp_server.logger import logger


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
        
        # Import the vector index manager
        from ipfs_datasets_py.ipfs_knn_index import IPFSKnnIndex
        
        # Infer dimension if not provided
        if dimension is None and vectors:
            dimension = len(vectors[0])
        
        # Create a vector index
        index = IPFSKnnIndex(dimension=dimension, metric=metric)
        
        # Convert vectors to numpy arrays
        np_vectors = np.array(vectors)
        
        # Add vectors to the index
        vector_ids = index.add_vectors(np_vectors, metadata=metadata)
        
        # Set the index ID and name if provided
        if index_id:
            index.index_id = index_id
        if index_name:
            index.index_name = index_name
            
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
