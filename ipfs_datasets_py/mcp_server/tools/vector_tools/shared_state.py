"""
Shared state management for MCP vector tools.

This module maintains state for vector indexes via ServerContext
or global fallback for backward compatibility.
"""

from __future__ import annotations
from typing import Any, Dict, Optional

# Global manager instance (deprecated - use ServerContext instead)
_global_manager = None

def _get_global_manager():
    """Get or create the global index manager.
    
    Note:
        Deprecated. New code should use ServerContext.get_vector_store() instead.
    """
    global _global_manager
    if _global_manager is None:
        from ipfs_datasets_py.ml.embeddings.ipfs_knn_index import IPFSKnnIndexManager
        _global_manager = IPFSKnnIndexManager()
    return _global_manager

def _reset_global_manager():
    """Reset the global manager (for testing purposes)."""
    global _global_manager
    _global_manager = None

# Main MCP functions for registration
async def get_global_manager(context: Optional["ServerContext"] = None) -> Dict[str, Any]:
    """Get or create the index manager.
    
    Args:
        context: Optional ServerContext. If provided, uses context's vector stores.
                Otherwise, falls back to global instance for backward compatibility.
    
    Returns:
        Status dict with manager information
        
    Note:
        The global instance is deprecated. New code should use ServerContext.
    """
    # If context provided, use it (new pattern)
    if context is not None:
        # Context manages vector stores via register_vector_store()
        return {
            "status": "success",
            "message": "Using ServerContext vector stores",
            "manager_available": True
        }
    
    # Fallback to global for backward compatibility (deprecated)
    global _global_manager
    if _global_manager is None:
        try:
            from ipfs_datasets_py.ml.embeddings.ipfs_knn_index import IPFSKnnIndexManager
            _global_manager = IPFSKnnIndexManager()
        except ImportError:
            _global_manager = None
            return {
                "status": "error",
                "message": "IPFSKnnIndexManager not available"
            }
    return {
        "status": "success",
        "message": "Global manager retrieved successfully",
        "manager_available": _global_manager is not None
    }

async def reset_global_manager():
    """Reset the global manager (for testing purposes)."""
    global _global_manager
    _global_manager = None
    return {
        "status": "success",
        "message": "Global manager reset successfully"
    }
