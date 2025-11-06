"""
Shared state management for MCP vector tools.

This module maintains global state for vector indexes to ensure
persistence between tool calls.
"""

# Global manager instance
_global_manager = None

def _get_global_manager():
    """Get or create the global index manager."""
    global _global_manager
    if _global_manager is None:
        from ipfs_datasets_py.ipfs_knn_index import IPFSKnnIndexManager
        _global_manager = IPFSKnnIndexManager()
    return _global_manager

def _reset_global_manager():
    """Reset the global manager (for testing purposes)."""
    global _global_manager
    _global_manager = None

# Main MCP functions for registration
async def get_global_manager():
    """Get or create the global index manager."""
    global _global_manager
    if _global_manager is None:
        try:
            from ipfs_datasets_py.ipfs_knn_index import IPFSKnnIndexManager
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
