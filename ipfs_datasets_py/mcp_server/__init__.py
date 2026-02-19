# ipfs_datasets_py/mcp_server/__init__.py
"""
MCP Server for IPFS Datasets Python.

This module provides Model Context Protocol server functionality to expose IPFS Datasets Python features
to AI assistants like Claude.

Usage:
    # Server Usage:
    # -------------
    # Start the server with default settings
    from ipfs_datasets_py.mcp_server import start_server
    start_server()

    # Or with custom settings
    start_server(host="127.0.0.1", port=5000, ipfs_kit_mcp_url="http://localhost:8001")

    # Or create and configure your own server instance
    from ipfs_datasets_py.mcp_server import IPFSDatasetsMCPServer
    server = IPFSDatasetsMCPServer()
    await server.register_tools()
    await server.register_ipfs_kit_tools()
    await server.start(host="127.0.0.1", port=5000)

    # Client Usage:
    # ------------
    # Connect to a running MCP server
    from ipfs_datasets_py.mcp_server import IPFSDatasetsMCPClient

    async def main():
        client = IPFSDatasetsMCPClient("http://localhost:8000")
        dataset_info = await client.load_dataset("/path/to/dataset.json")
"""

try:
    from .server import start_server, start_stdio_server, IPFSDatasetsMCPServer
except ImportError:
    # Fallback to simplified implementation if modelcontextprotocol is not available
    try:
        from .simple_server import start_simple_server as start_server
    except ImportError:
        # If neither server is available, provide placeholder
        def start_server(*args, **kwargs):
            raise ImportError(
                "MCP server dependencies not installed. "
                "Install with: pip install anyio mcp flask"
            )
    start_stdio_server = None
    IPFSDatasetsMCPServer = None

try:
    from .client import IPFSDatasetsMCPClient
except ImportError:
    # Client also depends on modelcontextprotocol
    IPFSDatasetsMCPClient = None

# These don't depend on modelcontextprotocol
from .configs import Configs, configs, load_config_from_yaml
try:
    from .simple_server import SimpleIPFSDatasetsMCPServer
except ImportError:
    SimpleIPFSDatasetsMCPServer = None

# MCP++ integration is always importable (with graceful fallback)
from . import mcplusplus

__version__ = "0.1.0"
__all__ = [
    "start_server",
    "start_stdio_server",
    "IPFSDatasetsMCPServer",
    "SimpleIPFSDatasetsMCPServer",
    "IPFSDatasetsMCPClient",
    "Configs",
    "configs",
    "load_config_from_yaml",
    "mcplusplus",
]
