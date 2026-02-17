"""
MCP tool for creating an index on a knowledge graph.

This is a thin wrapper around the core KnowledgeGraphManager class.
Core implementation: ipfs_datasets_py.core_operations.knowledge_graph_manager.KnowledgeGraphManager
"""

import logging
from typing import Dict, Any, Optional, List

logger = logging.getLogger(__name__)

from ipfs_datasets_py.core_operations import KnowledgeGraphManager


async def graph_index_create(
    index_name: str,
    entity_type: str,
    properties: List[str],
    driver_url: Optional[str] = None
) -> Dict[str, Any]:
    """
    Create an index on the knowledge graph.
    
    This is a thin wrapper around KnowledgeGraphManager.index_create().
    All business logic is in ipfs_datasets_py.core_operations.knowledge_graph_manager
    
    Args:
        index_name: Name for the index
        entity_type: Entity type to index (e.g., "Person", "Organization")
        properties: List of properties to index (e.g., ["name", "email"])
        driver_url: Optional URL for the graph database driver
    
    Returns:
        Dict containing:
        - status: "success" or "error"
        - index_name: Index name
        - entity_type: Entity type
        - properties: Indexed properties
        - message: Status message
    """
    try:
        url = driver_url or "ipfs://localhost:5001"
        manager = KnowledgeGraphManager(driver_url=url)
        result = await manager.index_create(index_name, entity_type, properties)
        return result
    except Exception as e:
        logger.error(f"Error in graph_index_create MCP tool: {e}")
        return {
            "status": "error",
            "message": str(e),
            "index_name": index_name
        }
