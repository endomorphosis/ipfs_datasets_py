"""
MCP tool for adding constraints to a knowledge graph.

This is a thin wrapper around the core KnowledgeGraphManager class.
Core implementation: ipfs_datasets_py.core_operations.knowledge_graph_manager.KnowledgeGraphManager
"""

import logging
from typing import Dict, Any, Optional, List

logger = logging.getLogger(__name__)

from ipfs_datasets_py.core_operations import KnowledgeGraphManager


async def graph_constraint_add(
    constraint_name: str,
    constraint_type: str,
    entity_type: str,
    properties: List[str],
    driver_url: Optional[str] = None
) -> Dict[str, Any]:
    """
    Add a constraint to the knowledge graph.
    
    This is a thin wrapper around KnowledgeGraphManager.constraint_add().
    All business logic is in ipfs_datasets_py.core_operations.knowledge_graph_manager
    
    Args:
        constraint_name: Name for the constraint
        constraint_type: Type of constraint ("unique", "exists", "node_key")
        entity_type: Entity type for the constraint (e.g., "Person", "Organization")
        properties: List of properties involved (e.g., ["email"])
        driver_url: Optional URL for the graph database driver
    
    Returns:
        Dict containing:
        - status: "success" or "error"
        - constraint_name: Constraint name
        - constraint_type: Constraint type
        - entity_type: Entity type
        - properties: Constrained properties
        - message: Status message
    """
    try:
        url = driver_url or "ipfs://localhost:5001"
        manager = KnowledgeGraphManager(driver_url=url)
        result = await manager.constraint_add(constraint_name, constraint_type, entity_type, properties)
        return result
    except Exception as e:
        logger.error(f"Error in graph_constraint_add MCP tool: {e}")
        return {
            "status": "error",
            "message": str(e),
            "constraint_name": constraint_name
        }
