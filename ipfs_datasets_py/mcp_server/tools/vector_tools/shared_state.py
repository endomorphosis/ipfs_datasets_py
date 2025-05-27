"""
Shared state management for MCP vector tools.

This module maintains global state for vector indexes to ensure
persistence between tool calls.
"""

# Global manager instance
_global_manager = None

def get_global_manager():
    """Get or create the global index manager."""
    global _global_manager
    if _global_manager is None:
        from ipfs_datasets_py.ipfs_knn_index import IPFSKnnIndexManager
        _global_manager = IPFSKnnIndexManager()
    return _global_manager

def reset_global_manager():
    """Reset the global manager (for testing purposes)."""
    global _global_manager
    _global_manager = None
