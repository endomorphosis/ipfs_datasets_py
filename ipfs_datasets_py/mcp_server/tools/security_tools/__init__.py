# ipfs_datasets_py/mcp_server/tools/security_tools/__init__.py
"""
Security tools for the MCP server.

These tools allow AI assistants to work with security features through the MCP protocol.
"""

from .check_access_permission import check_access_permission

__all__ = [
    "check_access_permission"
]
