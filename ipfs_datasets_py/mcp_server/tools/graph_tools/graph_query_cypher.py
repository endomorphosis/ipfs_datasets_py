"""
MCP tool for executing Cypher queries on a knowledge graph.

This is a thin wrapper around the core KnowledgeGraphManager class.
Core implementation: ipfs_datasets_py.core_operations.knowledge_graph_manager.KnowledgeGraphManager
"""

import logging
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

from ipfs_datasets_py.core_operations import KnowledgeGraphManager


async def graph_query_cypher(
    query: str,
    parameters: Optional[Dict[str, Any]] = None,
    driver_url: Optional[str] = None
) -> Dict[str, Any]:
    """
    Execute a Cypher query on the knowledge graph.
    
    This is a thin wrapper around KnowledgeGraphManager.query_cypher().
    All business logic is in ipfs_datasets_py.core_operations.knowledge_graph_manager
    
    Args:
        query: Cypher query string (e.g., "MATCH (n:Person) RETURN n LIMIT 10")
        parameters: Optional dictionary of query parameters
        driver_url: Optional URL for the graph database driver
    
    Returns:
        Dict containing:
        - status: "success" or "error"
        - query: The executed query
        - results: Query results
    """
    try:
        url = driver_url or "ipfs://localhost:5001"
        manager = KnowledgeGraphManager(driver_url=url)
        result = await manager.query_cypher(query, parameters)
        return result
    except Exception as e:
        logger.error(f"Error in graph_query_cypher MCP tool: {e}")
        return {
            "status": "error",
            "message": str(e),
            "query": query
        }
