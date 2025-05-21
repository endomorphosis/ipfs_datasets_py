# ipfs_datasets_py/mcp_server/tools/vector_tools/search_vector_index.py
"""
MCP tool for searching vector indexes.

This tool handles similarity search in vector indexes.
"""
import asyncio
from typing import Dict, Any, Optional, Union, List

import numpy as np

from ipfs_datasets_py.mcp_server.logger import logger


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
        
        # Import the vector index manager
        from ipfs_datasets_py.ipfs_knn_index import IPFSKnnIndexManager
        
        # Create a manager instance
        manager = IPFSKnnIndexManager()
        
        # Get the index
        index = manager.get_index(index_id)
        
        # Convert query vector to numpy array
        np_query = np.array(query_vector)
        
        # Search the index
        results = index.search(
            np_query, 
            top_k=top_k, 
            include_metadata=include_metadata,
            include_distances=include_distances,
            metadata_filter=filter_metadata
        )
        
        # Format results
        formatted_results = []
        for result in results:
            formatted_result = {
                "id": result.id
            }
            
            if include_distances:
                formatted_result["distance"] = float(result.score)  # Convert numpy float to Python float
                
            if include_metadata and result.metadata:
                formatted_result["metadata"] = result.metadata
                
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
