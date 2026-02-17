"""
MCP tool for beginning a knowledge graph transaction.

This is a thin wrapper around the core KnowledgeGraphManager class.
Core implementation: ipfs_datasets_py.core_operations.knowledge_graph_manager.KnowledgeGraphManager
"""

import logging
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

from ipfs_datasets_py.core_operations import KnowledgeGraphManager


async def graph_transaction_begin(driver_url: Optional[str] = None) -> Dict[str, Any]:
    """
    Begin a new transaction on the knowledge graph.
    
    This is a thin wrapper around KnowledgeGraphManager.transaction_begin().
    All business logic is in ipfs_datasets_py.core_operations.knowledge_graph_manager
    
    Args:
        driver_url: Optional URL for the graph database driver
    
    Returns:
        Dict containing:
        - status: "success" or "error"
        - transaction_id: Unique transaction identifier
        - message: Status message
    """
    try:
        url = driver_url or "ipfs://localhost:5001"
        manager = KnowledgeGraphManager(driver_url=url)
        result = await manager.transaction_begin()
        return result
    except Exception as e:
        logger.error(f"Error in graph_transaction_begin MCP tool: {e}")
        return {
            "status": "error",
            "message": str(e)
        }
