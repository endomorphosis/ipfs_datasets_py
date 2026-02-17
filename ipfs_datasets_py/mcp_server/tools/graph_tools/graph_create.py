"""
MCP tool for initializing a knowledge graph database.

This is a thin wrapper around the core KnowledgeGraphManager class.
Core implementation: ipfs_datasets_py.core_operations.knowledge_graph_manager.KnowledgeGraphManager
"""

import logging
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

from ipfs_datasets_py.core_operations import KnowledgeGraphManager


async def graph_create(driver_url: Optional[str] = None) -> Dict[str, Any]:
    """
    Create and initialize a knowledge graph database.
    
    This is a thin wrapper around KnowledgeGraphManager.initialize().
    All business logic is in ipfs_datasets_py.core_operations.knowledge_graph_manager
    
    Args:
        driver_url: Optional URL for the graph database driver (default: "ipfs://localhost:5001")
    
    Returns:
        Dict containing:
        - status: "success" or "error"
        - message: Status message
        - driver_url: The URL used for the driver
    """
    try:
        url = driver_url or "ipfs://localhost:5001"
        manager = KnowledgeGraphManager(driver_url=url)
        result = await manager.initialize()
        return result
    except Exception as e:
        logger.error(f"Error in graph_create MCP tool: {e}")
        return {
            "status": "error",
            "message": str(e)
        }
