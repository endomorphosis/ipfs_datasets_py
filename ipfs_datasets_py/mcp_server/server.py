#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
MCP Server for IPFS Datasets Python.

This module provides a Model Context Protocol server implementation for IPFS Datasets,
enabling AI models to interact with IPFS datasets through standardized tools.
"""
from __future__ import annotations

import argparse
import anyio
import importlib
import inspect
import os
from pathlib import Path
import sys
import traceback
from typing import Any, Callable, Dict, List, Optional, Union

import pydantic

# MCP is an optional dependency in some environments; avoid leaving globals
# undefined when imports fail so initialization fails clearly instead of with
# NameError.
try:
    from mcp.server import FastMCP
    from mcp.types import CallToolResult, TextContent, Tool
    from mcp import CallToolRequest
except ImportError as e:
    # Some environments add bundled third-party code to sys.path (e.g. ipfs_kit_py)
    # that includes a top-level 'mcp.py' module, which can shadow the real 'mcp'
    # package (that provides mcp.server/FastMCP). If we detect this, de-prioritize
    # those paths and retry the imports once.
    try:
        import sys as _sys
        import importlib as _importlib

        try:
            import mcp as _maybe_mcp
            _mcp_file = getattr(_maybe_mcp, "__file__", "") or ""
            _mcp_is_package = bool(getattr(_maybe_mcp, "__path__", None))
        except Exception:
            _mcp_file = ""
            _mcp_is_package = False

        _looks_like_ipfs_kit_shadow = False
        if _mcp_file:
            if _mcp_file.endswith("ipfs_kit_py/mcp.py") or ("ipfs_kit_py" in _mcp_file and _mcp_file.endswith("mcp.py")):
                _looks_like_ipfs_kit_shadow = True
            # ipfs_kit_py also ships a top-level `mcp/` package in its repo root.
            # If that repo root is on sys.path, it can shadow the real `mcp` PyPI
            # package (which provides `mcp.server`).
            if ("ipfs_kit_py" in _mcp_file) and ("/mcp/" in _mcp_file or _mcp_file.endswith("mcp/__init__.py")):
                _looks_like_ipfs_kit_shadow = True

        if _looks_like_ipfs_kit_shadow or not _mcp_is_package:
            _sys.modules.pop("mcp", None)

            # De-prioritize any path entries from ipfs_kit_py that provide a
            # top-level mcp.py or mcp/ package, since those mask the real 'mcp'
            # package.
            _shadow_paths: list[str] = []
            for _p in list(_sys.path):
                if not isinstance(_p, str) or not _p:
                    continue
                try:
                    if "ipfs_kit_py" not in _p:
                        continue
                    if Path(_p, "mcp.py").exists() or Path(_p, "mcp").is_dir():
                        _shadow_paths.append(_p)
                except Exception:
                    continue

            if _shadow_paths:
                _sys.path = [p for p in _sys.path if p not in _shadow_paths] + _shadow_paths

        _importlib.import_module("mcp.server")
        from mcp.server import FastMCP  # type: ignore[no-redef]
        from mcp.types import CallToolResult, TextContent, Tool  # type: ignore[no-redef]
        from mcp import CallToolRequest  # type: ignore[no-redef]
    except Exception:
        # Final fallback: leave MCP symbols undefined-but-present.
        FastMCP = None  # type: ignore[assignment]
        CallToolResult = None  # type: ignore[assignment]
        TextContent = None  # type: ignore[assignment]
        Tool = None  # type: ignore[assignment]
        CallToolRequest = None  # type: ignore[assignment]
        print(f"Failed to import mcp.server ({e}). Please ensure the mcp library is installed.")

from .configs import Configs, configs
from .logger import logger

from ipfs_datasets_py.utils.anyio_compat import run as run_anyio

# Import error reporting
try:
    from ..error_reporting import error_reporter, get_recent_logs
    ERROR_REPORTING_AVAILABLE = True
except ImportError:
    ERROR_REPORTING_AVAILABLE = False
    logger.warning("Error reporting module not available")






def return_text_content(input: Any, result_str: str) -> TextContent:
    """
    Return a TextContent object with formatted string.

    Args:
        string (str): The input string to be included in the content.
        result_str (str): A string identifier or label to prefix the input string.

    Returns:
        TextContent: A TextContent object with 'text' type and formatted text.
    """
    return TextContent(type="text", text=f"{result_str}: {repr(input)}") # NOTE we use repr to ensure special characters are handled correctly


def return_tool_call_results(content: TextContent, error: bool = False) -> CallToolResult:
    """
    Returns a CallToolResult object for tool call response.

    Args:
        content: The content of the tool call result.
        error: Whether the tool call resulted in an error. Defaults to False.

    Returns:
        CallToolResult: The formatted result object containing the content and error status.
    """
    return CallToolResult(isError=error, content=[content])


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
        this_is_valid_file = (
            item.is_file() and
            item.suffix == '.py' and # Only Python files
            not item.name.startswith('.') and # Avoid hidden and dunder files (e.g. __init__.py, __main__.py)
            not item.name.startswith('_')
        )

        if this_is_valid_file:
            module_name = item.stem
            try:
                module = importlib.import_module(f"ipfs_datasets_py.mcp_server.tools.{directory_path.name}.{module_name}")
                for attr_name in dir(module):
                    attr = getattr(module, attr_name)
                    # Only include functions defined in the module (not imported ones)
                    # and exclude built-in types and typing constructs
                    # For development tools, also include wrapped functions
                    this_is_valid_function = (
                        callable(attr) and
                        not attr_name.startswith('_') and
                        hasattr(attr, '__module__') and
                        hasattr(attr, '__doc__') and # Ensure it has a docstring, since Claude will need it to properly use a tool.
                        not attr_name in ['Dict', 'Any', 'Optional', 'Union', 'List', 'Tuple'] and
                        not isinstance(attr, type)  # Exclude classes/types
                    )

                    if this_is_valid_function:
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
    Model Context Protocol Server for IPFS Datasets Platform Integration

    The IPFSDatasetsMCPServer class provides a comprehensive Model Context Protocol
    (MCP) server implementation that enables AI models and applications to interact
    with IPFS-based datasets through standardized tool interfaces. This server acts
    as a bridge between AI systems and distributed dataset infrastructure, offering
    seamless access to content-addressable data storage, processing workflows, and
    analytical capabilities.

    The MCP server implements the complete Model Context Protocol specification,
    providing tool discovery, registration, execution, and monitoring capabilities
    for IPFS dataset operations. It supports dynamic tool loading, configuration
    management, error handling, and comprehensive logging for production-grade
    AI model integration workflows.

    Core Functionality:
    - Dynamic tool registration from multiple category directories
    - Standardized MCP protocol implementation for AI model compatibility
    - Comprehensive error handling and logging for debugging and monitoring
    - Configuration-driven behavior with flexible customization options
    - Asynchronous operation support for high-performance processing
    - Tool lifecycle management including registration, execution, and cleanup

    Tool Categories Supported:
    - Dataset Tools: Loading, processing, and managing IPFS-distributed datasets
    - IPFS Tools: Direct interaction with IPFS networks and content addressing
    - Vector Tools: Embedding generation, similarity search, and vector operations
    - Graph Tools: Knowledge graph construction and relationship analysis
    - Audit Tools: Data validation, quality assessment, and compliance checking
    - Media Tools: Audio/video processing and multimedia content analysis

    MCP Protocol Features:
    - Tool discovery and capability enumeration for client applications
    - Standardized tool execution with comprehensive input/output validation
    - Error reporting and status monitoring for reliable operation
    - Session management and context preservation across tool calls
    - Resource management and cleanup for efficient memory utilization

    Attributes:
        configs (Configs): Server configuration object containing operational
            parameters, tool settings, logging configuration, and resource limits
            for customizing server behavior and performance characteristics.
        mcp (FastMCP): Core MCP server instance implementing the Model Context
            Protocol specification with tool registration, execution, and
            communication capabilities for AI model integration.
        tools (Dict[str, Any]): Registry of available tools organized by category
            and identifier, containing tool metadata, execution handlers, and
            configuration parameters for dynamic tool management.

    Public Methods:
        register_tools() -> None:
            Discovers and registers all available tools from configured directories
        run_server() -> None:
            Starts the MCP server and begins accepting client connections
        get_tool_info(tool_id: str) -> Dict[str, Any]:
            Retrieves metadata and documentation for specific tools
        execute_tool(tool_request: CallToolRequest) -> CallToolResult:
            Executes requested tools with comprehensive error handling

    Usage Examples:
        # Basic server initialization and startup
        server = IPFSDatasetsMCPServer()
        await server.register_tools()
        await server.run_server()
        
        # Custom configuration with specific settings
        custom_config = Configs(
            log_level="DEBUG",
            max_workers=16,
            timeout=300
        )
        server = IPFSDatasetsMCPServer(server_configs=custom_config)
        await server.register_tools()
        
        # Development mode with enhanced debugging
        dev_server = IPFSDatasetsMCPServer()
        await dev_server.register_tools()
        # Server provides detailed logging and error reporting

    Integration Examples:
        # Claude/GPT model integration
        # The MCP server enables AI models to use tools through standard protocol:
        # - "Load the 'common_crawl' dataset from IPFS"
        # - "Generate embeddings for this text corpus"
        # - "Create a knowledge graph from this document collection"
        # - "Audit data quality across these distributed datasets"

    Dependencies:
        Required:
        - mcp: Model Context Protocol implementation library
        - pydantic: Data validation and configuration management
        - asyncio: Asynchronous programming support for concurrent operations
        
        Optional:
        - Various tool-specific dependencies loaded dynamically based on usage

    Notes:
        - Tools are discovered and registered automatically from configured directories
        - The server supports hot-reloading of tools for development workflows
        - Comprehensive error handling ensures robust operation in production environments
        - Configuration management supports environment-specific customization
        - Logging integration provides detailed operational visibility and debugging
        - Resource management prevents memory leaks and ensures efficient operation
        - Protocol compliance ensures compatibility with MCP-enabled AI systems
        - Tool execution is sandboxed for security and stability
    """

    def __init__(self, server_configs: Optional[Configs] = None):
        """
        Initialize IPFS Datasets MCP Server with Comprehensive Configuration

        Establishes a new Model Context Protocol server instance for IPFS dataset
        integration, configuring all necessary components for AI model interaction,
        tool management, and distributed dataset operations. This initialization
        prepares the server infrastructure while maintaining optimal performance
        and reliability characteristics.

        The initialization process sets up the core MCP server instance, configuration
        management, tool registry, logging systems, and resource allocation required
        for production-grade AI model integration. All subsystems are prepared for
        immediate tool registration and client connection handling.

        Args:
            server_configs (Optional[Configs], default=None): Server configuration
                object containing operational parameters, tool settings, logging
                configuration, and resource limits. If None, default configuration
                will be loaded from the global configs instance. Configuration
                includes:
                
                - log_level (str): Logging verbosity level (DEBUG, INFO, WARNING, ERROR)
                - max_workers (int): Maximum concurrent tool execution threads
                - timeout (int): Default timeout for tool execution in seconds
                - tool_directories (List[str]): Paths to scan for available tools
                - resource_limits (Dict[str, Any]): Memory and CPU usage constraints
                - security_settings (Dict[str, Any]): Authentication and authorization
                - performance_options (Dict[str, Any]): Optimization and caching settings
                
                Example: Configs(
                    log_level="INFO",
                    max_workers=8,
                    timeout=120,
                    tool_directories=["dataset_tools", "ipfs_tools"],
                    resource_limits={"max_memory": "4GB", "max_cpu": 80}
                )

        Attributes Initialized:
            configs (Configs): Server configuration with validated parameters and
                default value resolution for operational consistency.
            mcp (FastMCP): Core MCP server instance implementing protocol specification
                with tool registration, execution, and communication capabilities.
            tools (Dict[str, Any]): Empty tool registry prepared for dynamic tool
                discovery and registration from configured directories.

        Raises:
            ConfigurationError: If the provided server_configs contain invalid
                parameters, missing required settings, or incompatible values
                that prevent proper server initialization.
            ImportError: If required MCP protocol dependencies or core libraries
                are not available for server operation and tool management.
            ResourceError: If system resources are insufficient for the requested
                configuration including memory allocation or thread pool creation.

        Examples:
            # Basic initialization with default configuration
            server = IPFSDatasetsMCPServer()
            
            # Custom configuration for development environment
            dev_config = Configs(
                log_level="DEBUG",
                max_workers=4,
                timeout=60,
                development_mode=True
            )
            dev_server = IPFSDatasetsMCPServer(server_configs=dev_config)
            
            # Production configuration with enhanced performance
            prod_config = Configs(
                log_level="INFO",
                max_workers=16,
                timeout=300,
                resource_limits={"max_memory": "8GB"},
                security_settings={"enable_auth": True}
            )
            prod_server = IPFSDatasetsMCPServer(server_configs=prod_config)

        Notes:
            - Server initialization prepares infrastructure but does not start listening
            - Tool registration must be called separately after initialization
            - Configuration validation ensures parameter compatibility and security
            - Resource allocation is optimized based on configuration parameters
            - Logging integration is established immediately for debugging and monitoring
            - Default configurations provide secure and performant operation
            - Custom configurations enable environment-specific optimization
        """
        self.configs = server_configs or configs

        # Initialize error reporting
        if ERROR_REPORTING_AVAILABLE:
            try:
                error_reporter.install_global_handler()
                logger.info("Error reporting enabled - runtime errors will be reported to GitHub")
            except Exception as e:
                logger.warning(f"Failed to install error reporter: {e}")

        # Initialize MCP server
        if FastMCP is None:
            raise ImportError("MCP dependency is not available (FastMCP import failed). Install the 'mcp' package to use the MCP server.")
        self.mcp = FastMCP("ipfs_datasets")

        # Dictionary to store registered tools
        self.tools = {}

    async def register_tools(self):
        """Register all tools with the MCP server."""
        # Register tools from the tools directory
        tools_path = Path(__file__).parent / "tools"

        # Register tools from subdirectories
        tool_subdirs = [
            "dataset_tools", "ipfs_tools", "vector_tools", "graph_tools", "audit_tools", "media_tools", "investigation_tools", "legal_dataset_tools"
        ]
        
        for subdir in tool_subdirs:
            self._register_tools_from_subdir(tools_path / subdir)

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
        
        # Register software engineering tools
        self._register_tools_from_subdir(tools_path / "software_engineering_tools")

        # Register ipfs_embeddings_py tools (legacy integration)
        from .tools.ipfs_embeddings_integration import register_ipfs_embeddings_tools
        await register_ipfs_embeddings_tools(self.mcp, self.tools)

        logger.info(f"Registered {len(self.tools)} tools with the MCP server")

    def _register_tools_from_subdir(self, subdir_path: Path):
        """
        Register all tools from a subdirectory.

        Args:
            subdir_path: Path to the subdirectory containing tools
        """
        tools = import_tools_from_directory(subdir_path)

        for tool_name, tool_func in tools.items():
            # Wrap tool with error reporting if available
            if ERROR_REPORTING_AVAILABLE:
                wrapped_func = self._wrap_tool_with_error_reporting(tool_name, tool_func)
                self.mcp.add_tool(
                    wrapped_func, name=tool_name, description=tool_func.__doc__
                )
                self.tools[tool_name] = wrapped_func
            else:
                self.mcp.add_tool(
                    tool_func, name=tool_name, description=tool_func.__doc__
                )
                self.tools[tool_name] = tool_func
            logger.info(f"Registered tool: {tool_name}")
    
    def _wrap_tool_with_error_reporting(self, tool_name: str, tool_func: Callable) -> Callable:
        """
        Wrap a tool function with error reporting.
        
        Args:
            tool_name: Name of the tool
            tool_func: Tool function to wrap
            
        Returns:
            Wrapped function with error reporting
        """
        import functools
        
        @functools.wraps(tool_func)
        async def async_wrapper(*args, **kwargs):
            try:
                # If the function is async, await it
                if inspect.iscoroutinefunction(tool_func):
                    return await tool_func(*args, **kwargs)
                else:
                    return tool_func(*args, **kwargs)
            except Exception as e:
                # Report error to GitHub
                try:
                    logs = get_recent_logs()
                    error_reporter.report_error(
                        e,
                        source=f"MCP Tool: {tool_name}",
                        additional_info=f"Tool arguments: {kwargs}",
                        logs=logs,
                    )
                except Exception as report_err:
                    logger.error(f"Failed to report error: {report_err}")
                # Re-raise the original exception
                raise
        
        @functools.wraps(tool_func)
        def sync_wrapper(*args, **kwargs):
            try:
                return tool_func(*args, **kwargs)
            except Exception as e:
                # Report error to GitHub
                try:
                    logs = get_recent_logs()
                    error_reporter.report_error(
                        e,
                        source=f"MCP Tool: {tool_name}",
                        additional_info=f"Tool arguments: {kwargs}",
                        logs=logs,
                    )
                except Exception as report_err:
                    logger.error(f"Failed to report error: {report_err}")
                # Re-raise the original exception
                raise
        
        # Return appropriate wrapper based on whether function is async
        if inspect.iscoroutinefunction(tool_func):
            return async_wrapper
        else:
            return sync_wrapper

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
            from mcp.client import MCPClient # TODO FIXME This library is hallucinated! It does not exist!

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
        await self.register_tools()

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
        await self.register_tools()

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
        anyio.run(server.start_stdio())
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
        anyio.run(server.start(host, port))
    except KeyboardInterrupt:
        logger.info("Server stopped by user")
    except Exception as e:
        logger.error(f"Error starting server: {e}")
        traceback.print_exc()

class Args(pydantic.BaseModel):
    """
    Expected command-line arguments for the MCP server

    Attributes:
        host (str): The host address for the MCP server to bind to.
        port (int): The port number for the MCP server to listen on.
        ipfs_kit_mcp_url (Optional[pydantic.AnyUrl]): Optional URL for the IPFS Kit MCP service.
        configs (Optional[pydantic.FilePath]): Optional path to configuration file.

    Args:
        namespace (argparse.Namespace): The parsed command-line arguments namespace
            containing the configuration values to be validated and stored.
    """
    host: str
    port: int
    ipfs_kit_mcp_url: Optional[pydantic.AnyUrl] = None
    config: Optional[pydantic.FilePath] = None

    def __init__(self, namespace: argparse.Namespace):
        super().__init__(
            host=namespace.host,
            port=namespace.port,
            ipfs_kit_mcp_url=namespace.ipfs_kit_mcp_url,
            configs=namespace.config
        )

def main():
    """Command-line entry point."""
    parser = argparse.ArgumentParser(description="IPFS Datasets MCP Server")
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind the server to")
    parser.add_argument("--port", type=int, default=8000, help="Port to bind the server to")
    parser.add_argument("--ipfs-kit-mcp-url", help="URL of an ipfs_kit_py MCP server")
    parser.add_argument("--config", help="Path to a configuration YAML file")

    args = Args(parser.parse_args())

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
            anyio.run(server.start(host, port))
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
