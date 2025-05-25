# ipfs_datasets_py/mcp_server/tools/provenance_tools/__init__.py
"""
Data provenance tools for the MCP server.

These tools allow AI assistants to work with data provenance through the MCP protocol.
"""

from .record_provenance import record_provenance

__all__ = [
    "record_provenance"
]
