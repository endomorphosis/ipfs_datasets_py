#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Simplified MCP Server implementation for IPFS Datasets Python.

.. deprecated::
    This module is **deprecated** and will be removed in a future release.

    The Flask-based HTTP server is **not the intended access method** for this
    project.  All tool access should go through one of the three supported
    interfaces:

    1. **MCP stdio server** (recommended for AI assistants / VS Code):

       .. code-block:: bash

           python -m ipfs_datasets_py.mcp_server

    2. **CLI tool** (recommended for shell users):

       .. code-block:: bash

           ipfs-datasets <command>

    3. **Python package imports** (recommended for programmatic use):

       .. code-block:: python

           from ipfs_datasets_py import DatasetManager

    If you need HTTP access, use the FastAPI service layer
    (``ipfs_datasets_py.mcp_server.fastapi_service``) which is built on
    anyio/uvicorn and integrates properly with the MCP+P2P stack.
"""
from __future__ import annotations

import argparse
import importlib
import json
import os
import warnings
from pathlib import Path
import sys
from typing import Any, Callable, Dict, List, Optional, Union

try:
    from flask import Flask, request, jsonify
    FLASK_AVAILABLE = True
except ImportError:
    FLASK_AVAILABLE = False

    def Flask(*args, **kwargs):  # type: ignore[misc]
        raise ImportError(
            "Flask is not installed.  This module is deprecated — use "
            "`python -m ipfs_datasets_py.mcp_server` (MCP stdio) instead."
        )

    def request(*args, **kwargs):  # type: ignore[misc]
        raise ImportError("Flask is not installed.")

    def jsonify(*args, **kwargs):  # type: ignore[misc]
        raise ImportError("Flask is not installed.")

from ipfs_datasets_py.utils.anyio_compat import run as run_anyio

# Local imports
from ipfs_datasets_py.mcp_server.configs import Configs, configs
from ipfs_datasets_py.mcp_server.logger import logger
from ipfs_datasets_py.mcp_server.exceptions import (
    ToolExecutionError,
    ToolNotFoundError,
    ConfigurationError,
)

class SimpleCallResult:
    """Simple representation of a tool call result."""

    def __init__(self, result: Any, error: Optional[str] = None):
        self.result = result
        self.error = error

    def to_dict(self) -> Dict[str, Any]:
        """Convert the result to a dictionary."""
        if self.error:
            return {"success": False, "error": self.error}
        return {"success": True, "result": self.result}


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
        if item.is_file() and item.suffix == '.py' and item.name != '__init__.py' and not item.name.startswith('.') and not item.name.startswith('_'):
            module_name = item.stem
            try:
                module = importlib.import_module(f"ipfs_datasets_py.mcp_server.tools.{directory_path.name}.{module_name}")
                for attr_name in dir(module):
                    attr = getattr(module, attr_name)
                    if callable(attr) and not attr_name.startswith('_'):
                        tools[attr_name] = attr
            except ImportError as e:
                logger.error(f"Failed to import {module_name}: {e}")

    return tools



def import_argparse_program(directory_path: Path) -> Dict[str, Any]:
    """
    Import argparse programs from a directory.

    Args:
        program_name: Name of the program to import

    Returns:
        Callable function representing the program
    """
    program_name = None
    try:
        module = importlib.import_module(program_name)
        return getattr(module, 'main', None)
    except ImportError as e:
        logger.error(f"Failed to import program {program_name}: {e}")
        return None




class SimpleIPFSDatasetsMCPServer:
    """
    Simplified MCP Server for IPFS Datasets Python.

    .. deprecated::
        Use ``python -m ipfs_datasets_py.mcp_server`` (MCP stdio) or the
        ``ipfs-datasets`` CLI tool instead of this Flask-based HTTP server.
        See module docstring for full migration guide.
    """

    def __init__(self, server_configs: Optional[Configs] = None):
        """
        Initialize the Simple IPFS Datasets MCP Server.

        Args:
            server_configs: Optional configuration object. If not provided, the default configs will be used.
        """
        warnings.warn(
            "SimpleIPFSDatasetsMCPServer is deprecated.  Use "
            "`python -m ipfs_datasets_py.mcp_server` (MCP stdio) or the "
            "`ipfs-datasets` CLI instead of this Flask-based HTTP server.",
            DeprecationWarning,
            stacklevel=2,
        )
        if not FLASK_AVAILABLE:
            raise ImportError(
                "Flask is required for SimpleIPFSDatasetsMCPServer but is not installed. "
                "Install it with `pip install flask` or — better — migrate to the MCP "
                "stdio server: `python -m ipfs_datasets_py.mcp_server`."
            )
        self.configs = server_configs or configs

        # Initialize Flask app
        self.app = Flask("ipfs_datasets_mcp")

        # Dictionary to store registered tools
        self.tools = {}

        # Register routes
        self._register_routes()

    def _register_routes(self):
        """Register the Flask routes."""

        @self.app.route("/", methods=["GET"])
        def root():
            """Root endpoint."""
            return jsonify({
                "name": "IPFS Datasets MCP Server",
                "version": "0.1.0",
                "status": "healthy"
            })

        @self.app.route("/tools", methods=["GET"])
        def list_tools():
            """List available tools."""
            tool_info = {}
            for tool_name, tool_func in self.tools.items():
                tool_info[tool_name] = {
                    "name": tool_name,
                    "description": tool_func.__doc__ or "No description available"
                }
            return jsonify({"tools": tool_info})

        @self.app.route("/tools/<tool_name>", methods=["POST"])
        def call_tool(tool_name):
            """Call a specific tool with parameters."""
            if tool_name not in self.tools:
                return jsonify({"error": f"Tool '{tool_name}' not found"}), 404

            try:
                # Parse parameters from JSON
                params = request.json or {}

                # Call the tool function with the parameters
                tool_func = self.tools[tool_name]
                result = tool_func(**params)

                # Handle async functions
                if hasattr(result, "__await__"):
                    import anyio
                    result = anyio.run(result)

                return jsonify({"result": result})
            except ToolNotFoundError as e:
                logger.error(f"Tool not found: {e}")
                return jsonify({"error": f"Tool '{tool_name}' not found"}), 404
            except ToolExecutionError as e:
                logger.error(f"Tool execution error: {e}", exc_info=True)
                return jsonify({"error": f"Tool '{tool_name}' execution failed"}), 500
            except (TypeError, ValueError) as e:
                logger.error(f"Invalid parameters for tool {tool_name}: {e}", exc_info=True)
                return jsonify({"error": "Invalid parameters provided"}), 400
            except Exception as e:
                logger.error(f"Error calling tool {tool_name}: {e}", exc_info=True)
                return jsonify({"error": f"Internal server error while calling tool '{tool_name}'"}), 500

    def register_tools(self):
        """Register all tools with the MCP server."""
        # Register tools from the tools directory
        tools_path = Path(__file__).parent / "tools"

        # Register dataset tools
        self._register_tools_from_subdir(tools_path / "dataset_tools")

        try:
            # Register IPFS tools
            self._register_tools_from_subdir(tools_path / "ipfs_tools")
        except (ImportError, ModuleNotFoundError) as e:
            logger.warning(f"IPFS tools module not available: {e}")
        except ConfigurationError:
            raise
        except Exception as e:
            logger.error(f"Failed to register IPFS tools: {e}", exc_info=True)

        # Register vector tools
        self._register_tools_from_subdir(tools_path / "vector_tools")

        # Register graph tools
        self._register_tools_from_subdir(tools_path / "graph_tools")

        # Register audit tools
        self._register_tools_from_subdir(tools_path / "audit_tools")

        # Register security tools
        self._register_tools_from_subdir(tools_path / "security_tools")

        # Register provenance tools
        self._register_tools_from_subdir(tools_path / "provenance_tools")

        # Register embedding tools
        self._register_tools_from_subdir(tools_path / "embedding_tools")

        logger.info(f"Registered {len(self.tools)} tools with the MCP server")

    def _register_tools_from_subdir(self, subdir_path: Path):
        """
        Register all tools from a subdirectory.

        Args:
            subdir_path: Path to the subdirectory containing tools
        """
        tools = import_tools_from_directory(subdir_path)

        for tool_name, tool_func in tools.items():
            self.tools[tool_name] = tool_func
            logger.info(f"Registered tool: {tool_name}")

    def run(self, host: Optional[str] = None, port: Optional[int] = None):
        """
        Run the server.

        Args:
            host: Optional host to run the server on. Defaults to the configured host.
            port: Optional port to run the server on. Defaults to the configured port.
        """
        host = host or self.configs.host
        port = port or self.configs.port

        logger.info(f"Starting IPFS Datasets MCP Server on {host}:{port}")
        self.app.run(host=host, port=port, debug=self.configs.verbose)


def start_simple_server(config_path: Optional[str] = None):
    """
    Start the MCP server.

    .. deprecated::
        Use ``python -m ipfs_datasets_py.mcp_server`` (MCP stdio) or the
        ``ipfs-datasets`` CLI tool instead.

    Args:
        config_path: Optional path to a configuration file.
    """
    warnings.warn(
        "start_simple_server() is deprecated.  Use "
        "`python -m ipfs_datasets_py.mcp_server` (MCP stdio) or the "
        "`ipfs-datasets` CLI instead of this Flask-based HTTP server.",
        DeprecationWarning,
        stacklevel=2,
    )
    from .configs import load_config_from_yaml

    # Load configuration
    server_configs = load_config_from_yaml(config_path)

    # Create and initialize server
    server = SimpleIPFSDatasetsMCPServer(server_configs)
    server.register_tools()

    # Run the server
    server.run()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Start the IPFS Datasets MCP Server")
    parser.add_argument("--config", help="Path to configuration file")
    args = parser.parse_args()

    start_simple_server(args.config)
