#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
MCP Server for IPFS Datasets Python.

This module provides a Model Context Protocol server implementation for IPFS Datasets,
enabling AI models to interact with IPFS datasets through standardized tools.
"""
from __future__ import annotations

import argparse
import asyncio
import importlib
import os
from pathlib import Path
import sys
import traceback
from typing import Any, Callable, Dict, List, Optional, Union

from mcp.server import FastMCP
from mcp.types import Tool, TextContent
from mcp import CallToolRequest

from .configs import Configs, configs
from .logger import logger, mcp_logger

# Utility for importing tools
def import_tools_from_directory(directory_path: Path) -> Dict[str, Any]:
    """
    Import all tools from a directory.

    Args:
        directory_path: Path to the directory containing tools

    Returns:
        Dictionary of tool name -> tool function
    """
    tools = {}

    if not directory_path.exists() or not directory_path.is_dir():
        logger.warning(f"Directory {directory_path} does not exist or is not a directory")
        return tools

    for item in directory_path.iterdir():
        if item.is_file() and item.suffix == '.py' and item.name != '__init__.py':
            module_name = item.stem
            try:
                module = importlib.import_module(f"ipfs_datasets_py.mcp_server.tools.{directory_path.name}.{module_name}")
                for attr_name in dir(module):
                    attr = getattr(module, attr_name)
                    # Only include functions defined in the module (not imported ones)
                    # and exclude built-in types and typing constructs
                    # For development tools, also include wrapped functions
                    is_valid_function = (
                        callable(attr) and
                        not attr_name.startswith('_') and
                        hasattr(attr, '__module__') and
                        not attr_name in ['Dict', 'Any', 'Optional', 'Union', 'List', 'Tuple']
                    )

                    if is_valid_function:
                        # For development tools, be more flexible with module checking
                        is_from_module = (
                            attr.__module__ == module.__name__ or
                            (directory_path.name == 'development_tools' and
                             attr.__module__.endswith('development_tools.base_tool'))
                        )

                        if is_from_module:
                            tools[attr_name] = attr
                            logger.debug(f"Found tool function: {attr_name} in {module_name}")
            except ImportError as e:
                logger.error(f"Failed to import {module_name}: {e}")

    return tools


class IPFSDatasetsMCPServer:
    """
    MCP Server for IPFS Datasets Python.

    This class manages the MCP server and tool registration for IPFS Datasets.
    """

    def __init__(self, server_configs: Optional[Configs] = None):
        """
        Initialize the IPFS Datasets MCP Server.

        Args:
            server_configs: Optional configuration object. If not provided, the default configs will be used.
        """
        self.configs = server_configs or configs

        # Initialize MCP server
        self.mcp = FastMCP("ipfs_datasets")

        # Dictionary to store registered tools
        self.tools = {}

    def register_tools(self):
        """Register all tools with the MCP server."""
        # Register tools from the tools directory
        tools_path = Path(__file__).parent / "tools"

        # Register dataset tools
        self._register_tools_from_subdir(tools_path / "dataset_tools")

        # Register IPFS tools
        self._register_tools_from_subdir(tools_path / "ipfs_tools")

        # Register vector tools
        self._register_tools_from_subdir(tools_path / "vector_tools")

        # Register graph tools
        self._register_tools_from_subdir(tools_path / "graph_tools")

        # Register audit tools
        self._register_tools_from_subdir(tools_path / "audit_tools")

        # Register development tools (migrated from claudes_toolbox-1)
        try:
            dev_tools_path = tools_path / "development_tools"
            dev_tools_count = len(self.tools)
            self._register_tools_from_subdir(dev_tools_path)
            new_tools_count = len(self.tools) - dev_tools_count
            logger.info(f"Registered {new_tools_count} development tools from {dev_tools_path}")

            # Print details about registered development tools at debug level
            dev_tool_names = [name for name in self.tools.keys() if name in [
                'test_generator', 'codebase_search', 'documentation_generator',
                'lint_python_codebase', 'run_comprehensive_tests'
            ]]
            logger.debug(f"Registered development tools: {', '.join(dev_tool_names)}")

            # Verify expected development tools
            expected_dev_tools = {
                'test_generator', 'codebase_search', 'documentation_generator',
                'lint_python_codebase', 'run_comprehensive_tests'
            }
            missing_tools = expected_dev_tools - set(self.tools.keys())
            if missing_tools:
                logger.warning(f"Some expected development tools are missing: {', '.join(missing_tools)}")
        except Exception as e:
            logger.error(f"Error registering development tools: {e}")
            logger.debug(traceback.format_exc())

        # Register security tools
        self._register_tools_from_subdir(tools_path / "security_tools")

        # Register provenance tools
        self._register_tools_from_subdir(tools_path / "provenance_tools")

        # Register all new embedding and advanced tools
        self._register_tools_from_subdir(tools_path / "embedding_tools")
        self._register_tools_from_subdir(tools_path / "analysis_tools")
        self._register_tools_from_subdir(tools_path / "workflow_tools")
        self._register_tools_from_subdir(tools_path / "admin_tools")
        self._register_tools_from_subdir(tools_path / "cache_tools")
        self._register_tools_from_subdir(tools_path / "monitoring_tools")
        self._register_tools_from_subdir(tools_path / "sparse_embedding_tools")
        self._register_tools_from_subdir(tools_path / "background_task_tools")
        self._register_tools_from_subdir(tools_path / "auth_tools")
        self._register_tools_from_subdir(tools_path / "session_tools")
        self._register_tools_from_subdir(tools_path / "rate_limiting_tools")
        self._register_tools_from_subdir(tools_path / "data_processing_tools")
        self._register_tools_from_subdir(tools_path / "index_management_tools")
        self._register_tools_from_subdir(tools_path / "vector_store_tools")
        self._register_tools_from_subdir(tools_path / "storage_tools")
        self._register_tools_from_subdir(tools_path / "web_archive_tools")
        self._register_tools_from_subdir(tools_path / "ipfs_cluster_tools")

        # Register ipfs_embeddings_py tools (legacy integration)
        from .tools.ipfs_embeddings_integration import register_ipfs_embeddings_tools
        asyncio.run(register_ipfs_embeddings_tools(self.mcp, self.tools))

        logger.info(f"Registered {len(self.tools)} tools with the MCP server")

    def _register_tools_from_subdir(self, subdir_path: Path):
        """
        Register all tools from a subdirectory.

        Args:
            subdir_path: Path to the subdirectory containing tools
        """
        tools = import_tools_from_directory(subdir_path)

        for tool_name, tool_func in tools.items():
            self.mcp.add_tool(tool_func, name=tool_name)
            self.tools[tool_name] = tool_func
            logger.info(f"Registered tool: {tool_name}")

    def register_ipfs_kit_tools(self, ipfs_kit_mcp_url: Optional[str] = None):
        """
        Register tools from ipfs_kit_py.

        This can either register direct imports of ipfs_kit_py functions
        or set up proxies to an existing ipfs_kit_py MCP server.

        Args:
            ipfs_kit_mcp_url: Optional URL of an ipfs_kit_py MCP server.
                              If provided, tools will be proxied to this server.
                              If not provided, ipfs_kit_py functions will be imported directly.
        """
        if ipfs_kit_mcp_url:
            self._register_ipfs_kit_mcp_client(ipfs_kit_mcp_url)
        else:
            self._register_direct_ipfs_kit_imports()

    def _register_ipfs_kit_mcp_client(self, ipfs_kit_mcp_url: str):
        """
        Register proxy tools that connect to an ipfs_kit_py MCP server.

        Args:
            ipfs_kit_mcp_url: URL of the ipfs_kit_py MCP server
        """
        try:
            from mcp.client import MCPClient

            # Create MCP client
            client = MCPClient(ipfs_kit_mcp_url)

            # Get available tools from the server
            tools_info = client.get_tool_list()

            for tool_info in tools_info:
                tool_name = tool_info["name"]

                # Create proxy function
                async def proxy_tool(tool_name=tool_name, **kwargs):
                    try:
                        result = await client.call_tool(tool_name, kwargs)
                        return result
                    except Exception as e:
                        logger.error(f"Error calling {tool_name}: {e}")
                        return {"error": str(e)}

                # Register proxy with MCP server
                self.mcp.add_tool(proxy_tool, name=f"ipfs_kit_{tool_name}")
                self.tools[f"ipfs_kit_{tool_name}"] = proxy_tool
                logger.info(f"Registered ipfs_kit proxy tool: ipfs_kit_{tool_name}")

        except ImportError:
            logger.error("Failed to import modelcontextprotocol.client. Cannot register ipfs_kit MCP client.")
        except Exception as e:
            logger.error(f"Error registering ipfs_kit MCP client: {e}")

    def _register_direct_ipfs_kit_imports(self):
        """Register direct imports of ipfs_kit_py functions."""
        try:
            # Import ipfs_kit_py functions
            import ipfs_kit_py

            # Register core IPFS functions
            for func_name in ['add', 'cat', 'get', 'ls', 'pin_add', 'pin_ls', 'pin_rm']:
                if hasattr(ipfs_kit_py, func_name):
                    func = getattr(ipfs_kit_py, func_name)
                    self.mcp.add_tool(func, name=f"ipfs_kit_{func_name}")
                    self.tools[f"ipfs_kit_{func_name}"] = func
                    logger.info(f"Registered direct ipfs_kit tool: ipfs_kit_{func_name}")

        except ImportError:
            logger.error("Failed to import ipfs_kit_py. Cannot register direct ipfs_kit functions.")
        except Exception as e:
            logger.error(f"Error registering direct ipfs_kit functions: {e}")

    async def start_stdio(self):
        """
        Start the MCP server in stdio mode for VS Code integration.
        """
        # Register all tools
        self.register_tools()

        # Register ipfs_kit tools based on configuration
        if self.configs.ipfs_kit_mcp_url:
            self.register_ipfs_kit_tools(self.configs.ipfs_kit_mcp_url)
        else:
            self.register_ipfs_kit_tools()

        # Start the server in stdio mode
        await self.mcp.run_stdio_async()
        logger.info("MCP server started in stdio mode")

    async def start(self, host: str = "0.0.0.0", port: int = 8000):
        """
        Start the MCP server in HTTP mode (legacy).

        Args:
            host: Host to bind the server to
            port: Port to bind the server to
        """
        # Register all tools
        self.register_tools()

        # Register ipfs_kit tools based on configuration
        if self.configs.ipfs_kit_mcp_url:
            self.register_ipfs_kit_tools(self.configs.ipfs_kit_mcp_url)
        else:
            self.register_ipfs_kit_tools()

        # Start the server - FastMCP doesn't support host/port parameters, use stdio mode
        logger.warning("HTTP mode not supported by current FastMCP version, falling back to stdio mode")
        await self.mcp.run_stdio_async()
        logger.info(f"MCP server started in stdio mode")


def start_stdio_server(ipfs_kit_mcp_url: Optional[str] = None):
    """
    Start the IPFS Datasets MCP server in stdio mode for VS Code integration.

    Args:
        ipfs_kit_mcp_url: Optional URL of an ipfs_kit_py MCP server.
                         If provided, tools will be proxied to this server.
    """
    # Update the configuration if ipfs_kit_mcp_url is provided
    if ipfs_kit_mcp_url:
        configs.ipfs_kit_mcp_url = ipfs_kit_mcp_url
        configs.ipfs_kit_integration = "mcp"

    # Create server
    server = IPFSDatasetsMCPServer()

    # Start server in stdio mode
    try:
        logger.info("Starting MCP server in stdio mode")
        asyncio.run(server.start_stdio())
    except KeyboardInterrupt:
        logger.info("Server stopped by user")
    except Exception as e:
        logger.error(f"Error starting stdio server: {e}")
        traceback.print_exc()


def start_server(host: str = "0.0.0.0", port: int = 8000, ipfs_kit_mcp_url: Optional[str] = None):
    """
    Start the IPFS Datasets MCP server in HTTP mode (legacy).

    Args:
        host: Host to bind the server to
        port: Port to bind the server to
        ipfs_kit_mcp_url: Optional URL of an ipfs_kit_py MCP server.
                         If provided, tools will be proxied to this server.
    """
    # Update the configuration if ipfs_kit_mcp_url is provided
    if ipfs_kit_mcp_url:
        configs.ipfs_kit_mcp_url = ipfs_kit_mcp_url
        configs.ipfs_kit_integration = "mcp"

    # Create server
    server = IPFSDatasetsMCPServer()

    # Start server
    try:
        logger.info(f"Starting server at {host}:{port}")
        asyncio.run(server.start(host, port))
    except KeyboardInterrupt:
        logger.info("Server stopped by user")
    except Exception as e:
        logger.error(f"Error starting server: {e}")
        traceback.print_exc()


def main():
    """Command-line entry point."""
    parser = argparse.ArgumentParser(description="IPFS Datasets MCP Server")
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind the server to")
    parser.add_argument("--port", type=int, default=8000, help="Port to bind the server to")
    parser.add_argument("--ipfs-kit-mcp-url", help="URL of an ipfs_kit_py MCP server")
    parser.add_argument("--config", help="Path to a configuration YAML file")

    args = parser.parse_args()

    # Load custom configuration if provided
    if args.config:
        from .configs import load_config_from_yaml
        custom_configs = load_config_from_yaml(args.config)

        # Override with command line arguments if provided
        if args.ipfs_kit_mcp_url:
            custom_configs.ipfs_kit_mcp_url = args.ipfs_kit_mcp_url
            custom_configs.ipfs_kit_integration = "mcp"

        # Apply host and port from command line arguments
        host = args.host if args.host else custom_configs.host
        port = args.port if args.port else custom_configs.port

        # Create server with custom configuration
        server = IPFSDatasetsMCPServer(custom_configs)
        try:
            asyncio.run(server.start(host, port))
        except KeyboardInterrupt:
            logger.info("Server stopped by user")
        except Exception as e:
            logger.error(f"Error starting server: {e}")
            traceback.print_exc()
    else:
        # Use default configuration
        try:
            start_server(args.host, args.port, args.ipfs_kit_mcp_url)
        except KeyboardInterrupt:
            logger.info("Server stopped by user")
        except Exception as e:
            logger.error(f"Error starting server: {e}")
            traceback.print_exc()


if __name__ == "__main__":
    main()
