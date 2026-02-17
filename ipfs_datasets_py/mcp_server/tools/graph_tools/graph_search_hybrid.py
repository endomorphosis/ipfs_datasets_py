"""
MCP tool for performing hybrid search on a knowledge graph.

This is a thin wrapper around the core KnowledgeGraphManager class.
Core implementation: ipfs_datasets_py.core_operations.knowledge_graph_manager.KnowledgeGraphManager
"""

import logging
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

from ipfs_datasets_py.core_operations import KnowledgeGraphManager


async def graph_search_hybrid(
    query: str,
    search_type: str = "semantic",
    limit: int = 10,
    driver_url: Optional[str] = None
) -> Dict[str, Any]:
    """
    Perform hybrid search on the knowledge graph.
    
    This is a thin wrapper around KnowledgeGraphManager.hybrid_search().
    All business logic is in ipfs_datasets_py.core_operations.knowledge_graph_manager
    
    Args:
        query: Search query string
        search_type: Type of search - "semantic", "keyword", or "hybrid" (default: "semantic")
        limit: Maximum number of results to return (default: 10)
        driver_url: Optional URL for the graph database driver
    
    Returns:
        Dict containing:
        - status: "success" or "error"
        - query: The search query
        - search_type: Type of search performed
        - results: Search results
        - count: Number of results returned
    """
    try:
        url = driver_url or "ipfs://localhost:5001"
        manager = KnowledgeGraphManager(driver_url=url)
        result = await manager.hybrid_search(query, search_type, limit)
        return result
    except Exception as e:
        logger.error(f"Error in graph_search_hybrid MCP tool: {e}")
        return {
            "status": "error",
            "message": str(e),
            "query": query
        }
