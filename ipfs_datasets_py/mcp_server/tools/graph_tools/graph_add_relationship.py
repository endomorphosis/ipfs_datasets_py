"""
MCP tool for adding relationships to a knowledge graph.

This is a thin wrapper around the core KnowledgeGraphManager class.
Core implementation: ipfs_datasets_py.core_operations.knowledge_graph_manager.KnowledgeGraphManager
"""

import logging
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

from ipfs_datasets_py.core_operations import KnowledgeGraphManager


async def graph_add_relationship(
    source_id: str,
    target_id: str,
    relationship_type: str,
    properties: Optional[Dict[str, Any]] = None,
    driver_url: Optional[str] = None
) -> Dict[str, Any]:
    """
    Add a relationship between entities in the knowledge graph.
    
    This is a thin wrapper around KnowledgeGraphManager.add_relationship().
    All business logic is in ipfs_datasets_py.core_operations.knowledge_graph_manager
    
    Args:
        source_id: Source entity identifier
        target_id: Target entity identifier
        relationship_type: Type of relationship (e.g., "KNOWS", "WORKS_AT")
        properties: Optional dictionary of relationship properties
        driver_url: Optional URL for the graph database driver
    
    Returns:
        Dict containing:
        - status: "success" or "error"
        - source_id: Source entity ID
        - target_id: Target entity ID
        - relationship_type: Relationship type
        - properties: Relationship properties
    """
    try:
        url = driver_url or "ipfs://localhost:5001"
        manager = KnowledgeGraphManager(driver_url=url)
        result = await manager.add_relationship(source_id, target_id, relationship_type, properties)
        return result
    except Exception as e:
        logger.error(f"Error in graph_add_relationship MCP tool: {e}")
        return {
            "status": "error",
            "message": str(e),
            "source_id": source_id,
            "target_id": target_id
        }
