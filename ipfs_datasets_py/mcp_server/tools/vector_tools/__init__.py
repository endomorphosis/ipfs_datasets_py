# ipfs_datasets_py/mcp_server/tools/vector_tools/__init__.py
"""
Vector tools for the MCP server.

These tools allow AI assistants to work with vector indices through the MCP protocol.
"""

from .create_vector_index import create_vector_index
from .search_vector_index import search_vector_index

__all__ = [
    "create_vector_index",
    "search_vector_index"
]
