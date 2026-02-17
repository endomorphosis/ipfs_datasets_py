"""
MCP tool for adding entities to a knowledge graph.

This is a thin wrapper around the core KnowledgeGraphManager class.
Core implementation: ipfs_datasets_py.core_operations.knowledge_graph_manager.KnowledgeGraphManager
"""

import logging
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

from ipfs_datasets_py.core_operations import KnowledgeGraphManager


async def graph_add_entity(
    entity_id: str,
    entity_type: str,
    properties: Optional[Dict[str, Any]] = None,
    driver_url: Optional[str] = None
) -> Dict[str, Any]:
    """
    Add an entity to the knowledge graph.
    
    This is a thin wrapper around KnowledgeGraphManager.add_entity().
    All business logic is in ipfs_datasets_py.core_operations.knowledge_graph_manager
    
    Args:
        entity_id: Unique identifier for the entity
        entity_type: Type/label of the entity (e.g., "Person", "Organization")
        properties: Optional dictionary of entity properties
        driver_url: Optional URL for the graph database driver
    
    Returns:
        Dict containing:
        - status: "success" or "error"
        - entity_id: The entity identifier
        - entity_type: The entity type
        - properties: The entity properties
    """
    try:
        url = driver_url or "ipfs://localhost:5001"
        manager = KnowledgeGraphManager(driver_url=url)
        result = await manager.add_entity(entity_id, entity_type, properties)
        return result
    except Exception as e:
        logger.error(f"Error in graph_add_entity MCP tool: {e}")
        return {
            "status": "error",
            "message": str(e),
            "entity_id": entity_id
        }
