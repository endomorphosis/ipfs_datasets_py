# ipfs_datasets_py/mcp_server/tools/graph_tools/__init__.py
"""
Graph tools for the MCP server.

These tools allow AI assistants to work with knowledge graphs through the MCP protocol.
"""

from .query_knowledge_graph import query_knowledge_graph

__all__ = [
    "query_knowledge_graph"
]
