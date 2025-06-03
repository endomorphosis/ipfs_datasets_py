#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Simplified MCP Server implementation for IPFS Datasets Python.

This module provides a simpler server implementation that doesn't rely on the
modelcontextprotocol package, making it easier to test and integrate.
"""
from __future__ import annotations

import argparse
import importlib
import json
import os
from pathlib import Path
import sys
from typing import Any, Callable, Dict, List, Optional, Union

from flask import Flask, request, jsonify

# Local imports
from ipfs_datasets_py.mcp_server.configs import Configs, configs
from ipfs_datasets_py.mcp_server.logger import logger

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
    try:
        module = importlib.import_module(program_name)
        return getattr(module, 'main', None)
    except ImportError as e:
        logger.error(f"Failed to import program {program_name}: {e}")
        return None




class SimpleIPFSDatasetsMCPServer:
    """
    Simplified MCP Server for IPFS Datasets Python.

    This class provides a simpler server implementation that uses Flask directly
    and doesn't rely on the modelcontextprotocol package.
    """

    def __init__(self, server_configs: Optional[Configs] = None):
        """
        Initialize the Simple IPFS Datasets MCP Server.

        Args:
            server_configs: Optional configuration object. If not provided, the default configs will be used.
        """
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
                    import asyncio
                    result = asyncio.run(result)

                return jsonify({"result": result})
            except Exception as e:
                logger.error(f"Error calling tool {tool_name}: {e}")
                return jsonify({"error": str(e)}), 500

    def register_tools(self):
        """Register all tools with the MCP server."""
        # Register tools from the tools directory
        tools_path = Path(__file__).parent / "tools"

        # Register dataset tools
        self._register_tools_from_subdir(tools_path / "dataset_tools")

        try:
            # Register IPFS tools
            self._register_tools_from_subdir(tools_path / "ipfs_tools")
        except Exception as e:
            logger.error(f"Failed to register IPFS tools: {e}")

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

    Args:
        config_path: Optional path to a configuration file.
    """
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
