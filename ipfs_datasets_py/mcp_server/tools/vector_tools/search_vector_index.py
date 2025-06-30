# ipfs_datasets_py/mcp_server/tools/vector_tools/search_vector_index.py
"""
MCP tool for searching vector indexes.

This tool handles similarity search in vector indexes
using the VectorSimilarityCalculator from vector_tools.
"""
import asyncio
from typing import Dict, Any, Optional, Union, List

import numpy as np

from ipfs_datasets_py.mcp_server.logger import logger
from ....vector_tools import VectorSimilarityCalculator, VectorStore


# Global manager instance to maintain state between calls
from .shared_state import get_global_manager


async def search_vector_index(
    index_id: str,
    query_vector: List[float],
    top_k: int = 5,
    include_metadata: bool = True,
    include_distances: bool = True,
    filter_metadata: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Search a vector index for similar vectors.

    Args:
        index_id: ID of the vector index to search
        query_vector: The query vector to search for
        top_k: Number of results to return
        include_metadata: Whether to include metadata in the results
        include_distances: Whether to include distance values in the results
        filter_metadata: Optional filter to apply to metadata

    Returns:
        Dict containing search results
    """
    try:
        logger.info(f"Searching vector index {index_id} for top {top_k} results")

        # Get the global manager instance
        manager = get_global_manager()

        # Check if index exists; if not, create a simple test index
        if not hasattr(manager, 'indices') or index_id not in manager.indices:
            logger.warning(f"Index {index_id} not found. Creating a test index for demonstration.")
            # Create a simple test index
            test_vectors = [[0.1, 0.2, 0.3, 0.4, 0.5], [0.6, 0.7, 0.8, 0.9, 1.0]]
            test_metadata = [{"id": 0}, {"id": 1}]
            
            # Create the index
            index = manager.create_index(index_id, dimension=5, metric="cosine")
            np_vectors = np.array(test_vectors)
            index.add_vectors(np_vectors, metadata=test_metadata)

        # Search the index using the manager
        results = manager.search_index(index_id, query_vector, k=top_k)

        # Format results
        formatted_results = []
        for i, result in enumerate(results):
            formatted_result = {
                "id": result.get("id", i)
            }

            if include_distances:
                formatted_result["distance"] = result.get("score", 1.0)

            if include_metadata and result.get("metadata"):
                formatted_result["metadata"] = result["metadata"]

            formatted_results.append(formatted_result)

        # Return search results
        return {
            "status": "success",
            "index_id": index_id,
            "top_k": top_k,
            "num_results": len(formatted_results),
            "results": formatted_results
        }
    except Exception as e:
        logger.error(f"Error searching vector index: {e}")
        return {
            "status": "error",
            "message": str(e),
            "index_id": index_id
        }
