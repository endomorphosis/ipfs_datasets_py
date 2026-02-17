"""Hierarchical Tool Manager for MCP Server.

This module provides a hierarchical tool management system that reduces
context window usage by organizing tools into categories and providing
dynamic tool loading and dispatch.

Instead of registering 347+ tools at the top level, we register only:
- tools.list_categories (list all categories)
- tools.list_tools (list tools in a category)
- tools.get_schema (get schema for a specific tool)
- tools.dispatch (execute a tool)

This reduces context window usage by ~99% while maintaining full functionality.
"""

from __future__ import annotations

import importlib
import inspect
import logging
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple
import json

logger = logging.getLogger(__name__)


class ToolCategory:
    """Represents a category of tools."""
    
    def __init__(self, name: str, path: Path, description: str = ""):
        self.name = name
        self.path = path
        self.description = description
        self._tools: Dict[str, Callable] = {}
        self._tool_metadata: Dict[str, Dict[str, Any]] = {}
        self._discovered = False
    
    def discover_tools(self):
        """Discover all tools in this category."""
        if self._discovered:
            return
        
        if not self.path.exists():
            logger.warning(f"Category path does not exist: {self.path}")
            return
        
        # Import tools from Python files in this directory
        for tool_file in self.path.glob("*.py"):
            if tool_file.name.startswith('_') or tool_file.name == "__init__.py":
                continue
            
            tool_name = tool_file.stem
            module_path = self._get_module_path(tool_file)
            
            try:
                module = importlib.import_module(module_path)
                
                # Find callable functions in the module
                for name, obj in inspect.getmembers(module):
                    if not inspect.isfunction(obj):
                        continue
                    if name.startswith('_'):
                        continue
                    
                    # Use the tool name or the function that matches the file name
                    if name == tool_name or tool_name in name:
                        self._tools[name] = obj
                        self._tool_metadata[name] = {
                            "name": name,
                            "category": self.name,
                            "description": obj.__doc__ or "",
                            "signature": str(inspect.signature(obj))
                        }
                        logger.debug(f"Discovered tool: {self.name}.{name}")
                
            except Exception as e:
                logger.warning(f"Failed to load tool from {tool_file}: {e}")
        
        self._discovered = True
        logger.info(f"Discovered {len(self._tools)} tools in category '{self.name}'")
    
    def _get_module_path(self, file_path: Path) -> str:
        """Get the Python module path for a file."""
        # Convert file path to module path
        # e.g., /path/to/ipfs_datasets_py/mcp_server/tools/dataset_tools/load_dataset.py
        # -> ipfs_datasets_py.mcp_server.tools.dataset_tools.load_dataset
        
        parts = file_path.parts
        # Find the index of 'ipfs_datasets_py'
        try:
            idx = parts.index('ipfs_datasets_py')
            module_parts = parts[idx:]
            module_path = '.'.join(module_parts[:-1] + (file_path.stem,))
            return module_path
        except ValueError:
            # Fallback: use relative import
            return f"ipfs_datasets_py.mcp_server.tools.{self.name}.{file_path.stem}"
    
    def list_tools(self) -> List[Dict[str, Any]]:
        """List all tools in this category with minimal metadata."""
        if not self._discovered:
            self.discover_tools()
        
        return [
            {
                "name": name,
                "description": (metadata["description"].split('\n')[0] if metadata["description"] else "")[:100]
            }
            for name, metadata in self._tool_metadata.items()
        ]
    
    def get_tool(self, tool_name: str) -> Optional[Callable]:
        """Get a tool function by name."""
        if not self._discovered:
            self.discover_tools()
        
        return self._tools.get(tool_name)
    
    def get_tool_schema(self, tool_name: str) -> Optional[Dict[str, Any]]:
        """Get the full schema for a tool."""
        if not self._discovered:
            self.discover_tools()
        
        metadata = self._tool_metadata.get(tool_name)
        if not metadata:
            return None
        
        tool_func = self._tools.get(tool_name)
        if not tool_func:
            return None
        
        # Build full schema
        sig = inspect.signature(tool_func)
        parameters = {}
        
        for param_name, param in sig.parameters.items():
            param_info = {
                "name": param_name,
                "required": param.default == inspect.Parameter.empty,
            }
            
            # Try to get type annotation
            if param.annotation != inspect.Parameter.empty:
                param_info["type"] = str(param.annotation)
            
            # Get default value
            if param.default != inspect.Parameter.empty:
                param_info["default"] = str(param.default)
            
            parameters[param_name] = param_info
        
        return {
            **metadata,
            "parameters": parameters,
            "return_type": str(sig.return_annotation) if sig.return_annotation != inspect.Signature.empty else "Any"
        }


class HierarchicalToolManager:
    """Manages tools in a hierarchical structure to reduce context window usage.
    
    This manager organizes tools into categories and provides dynamic loading
    and dispatch capabilities. Instead of registering hundreds of tools with
    the MCP server, we register only 4 meta-tools that handle category listing,
    tool listing, schema retrieval, and tool dispatch.
    
    Usage:
        manager = HierarchicalToolManager()
        
        # List categories
        categories = await manager.list_categories()
        
        # List tools in a category
        tools = await manager.list_tools("dataset_tools")
        
        # Get tool schema
        schema = await manager.get_tool_schema("dataset_tools", "load_dataset")
        
        # Dispatch to a tool
        result = await manager.dispatch("dataset_tools", "load_dataset", 
                                       source="squad")
    """
    
    def __init__(self, tools_root: Optional[Path] = None):
        """Initialize the hierarchical tool manager.
        
        Args:
            tools_root: Root directory for tools. If None, uses default location.
        """
        if tools_root is None:
            tools_root = Path(__file__).parent / "tools"
        
        self.tools_root = tools_root
        self.categories: Dict[str, ToolCategory] = {}
        self._category_metadata: Dict[str, Dict[str, Any]] = {}
        self._discovered_categories = False
        
        # Load category metadata
        self._load_category_metadata()
    
    def _load_category_metadata(self):
        """Load metadata for all categories."""
        # This could be from JSON files, but for now we'll use defaults
        # Users can customize by creating category.json files
        pass
    
    def discover_categories(self):
        """Discover all tool categories."""
        if self._discovered_categories:
            return
        
        if not self.tools_root.exists():
            logger.warning(f"Tools root does not exist: {self.tools_root}")
            return
        
        for category_dir in self.tools_root.iterdir():
            if not category_dir.is_dir():
                continue
            if category_dir.name.startswith('_'):
                continue
            
            category_name = category_dir.name
            
            # Check for category metadata file
            metadata_file = category_dir / "category.json"
            description = ""
            if metadata_file.exists():
                try:
                    with open(metadata_file) as f:
                        metadata = json.load(f)
                        description = metadata.get("description", "")
                except Exception as e:
                    logger.warning(f"Failed to load metadata for {category_name}: {e}")
            
            # Create category
            category = ToolCategory(category_name, category_dir, description)
            self.categories[category_name] = category
            self._category_metadata[category_name] = {
                "name": category_name,
                "description": description,
                "path": str(category_dir)
            }
        
        self._discovered_categories = True
        logger.info(f"Discovered {len(self.categories)} tool categories")
    
    async def list_categories(self, include_count: bool = False) -> List[Dict[str, Any]]:
        """List all available tool categories.
        
        Args:
            include_count: Whether to include tool count for each category.
        
        Returns:
            List of category metadata dictionaries.
        """
        if not self._discovered_categories:
            self.discover_categories()
        
        result = []
        for name, metadata in self._category_metadata.items():
            cat_info = {
                "name": name,
                "description": metadata["description"]
            }
            
            if include_count:
                category = self.categories[name]
                if not category._discovered:
                    category.discover_tools()
                cat_info["tool_count"] = len(category._tools)
            
            result.append(cat_info)
        
        return sorted(result, key=lambda x: x["name"])
    
    async def list_tools(self, category: str) -> Dict[str, Any]:
        """List all tools in a category.
        
        Args:
            category: Name of the category.
        
        Returns:
            Dict with category info and list of tools.
        """
        if not self._discovered_categories:
            self.discover_categories()
        
        if category not in self.categories:
            return {
                "status": "error",
                "error": f"Category '{category}' not found",
                "available_categories": list(self.categories.keys())
            }
        
        cat = self.categories[category]
        tools = cat.list_tools()
        
        return {
            "status": "success",
            "category": category,
            "description": cat.description,
            "tool_count": len(tools),
            "tools": tools
        }
    
    async def get_tool_schema(self, category: str, tool: str) -> Dict[str, Any]:
        """Get the full schema for a specific tool.
        
        Args:
            category: Name of the category.
            tool: Name of the tool.
        
        Returns:
            Dict with tool schema or error.
        """
        if not self._discovered_categories:
            self.discover_categories()
        
        if category not in self.categories:
            return {
                "status": "error",
                "error": f"Category '{category}' not found"
            }
        
        cat = self.categories[category]
        schema = cat.get_tool_schema(tool)
        
        if schema is None:
            return {
                "status": "error",
                "error": f"Tool '{tool}' not found in category '{category}'"
            }
        
        return {
            "status": "success",
            "schema": schema
        }
    
    async def dispatch(
        self,
        category: str,
        tool: str,
        params: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Dispatch to a specific tool.
        
        Args:
            category: Name of the category.
            tool: Name of the tool.
            params: Parameters to pass to the tool.
        
        Returns:
            Tool execution result.
        """
        if not self._discovered_categories:
            self.discover_categories()
        
        if params is None:
            params = {}
        
        if category not in self.categories:
            return {
                "status": "error",
                "error": f"Category '{category}' not found",
                "available_categories": list(self.categories.keys())
            }
        
        cat = self.categories[category]
        tool_func = cat.get_tool(tool)
        
        if tool_func is None:
            available_tools = [t["name"] for t in cat.list_tools()]
            return {
                "status": "error",
                "error": f"Tool '{tool}' not found in category '{category}'",
                "available_tools": available_tools
            }
        
        try:
            # Get function signature
            sig = inspect.signature(tool_func)
            
            # Filter params to match function parameters
            filtered_params = {}
            for param_name in sig.parameters:
                if param_name in params:
                    filtered_params[param_name] = params[param_name]
            
            # Call the tool
            if inspect.iscoroutinefunction(tool_func):
                result = await tool_func(**filtered_params)
            else:
                result = tool_func(**filtered_params)
            
            # Ensure result is a dict
            if not isinstance(result, dict):
                result = {"status": "success", "result": str(result)}
            
            return result
            
        except Exception as e:
            logger.error(f"Error dispatching to {category}.{tool}: {e}", exc_info=True)
            return {
                "status": "error",
                "error": str(e),
                "category": category,
                "tool": tool
            }


# Create global instance (can be overridden for testing)
_global_manager: Optional[HierarchicalToolManager] = None


def get_tool_manager() -> HierarchicalToolManager:
    """Get the global hierarchical tool manager instance."""
    global _global_manager
    if _global_manager is None:
        _global_manager = HierarchicalToolManager()
    return _global_manager


# MCP tool wrappers for registration with FastMCP

async def tools_list_categories(include_count: bool = False) -> Dict[str, Any]:
    """List all available tool categories.
    
    This meta-tool provides access to the hierarchical tool system.
    Use this to discover what categories of tools are available.
    
    Args:
        include_count: Include tool count for each category.
    
    Returns:
        Dict with list of categories and their metadata.
    """
    manager = get_tool_manager()
    categories = await manager.list_categories(include_count=include_count)
    return {
        "status": "success",
        "category_count": len(categories),
        "categories": categories
    }


async def tools_list_tools(category: str) -> Dict[str, Any]:
    """List all tools in a specific category.
    
    After discovering categories with tools_list_categories, use this
    to see what tools are available in a specific category.
    
    Args:
        category: Name of the category to list tools from.
    
    Returns:
        Dict with tools in the category.
    """
    manager = get_tool_manager()
    return await manager.list_tools(category)


async def tools_get_schema(category: str, tool: str) -> Dict[str, Any]:
    """Get the full schema for a specific tool.
    
    Use this to get detailed information about a tool's parameters,
    return type, and documentation before calling it.
    
    Args:
        category: Category containing the tool.
        tool: Name of the tool.
    
    Returns:
        Dict with tool schema.
    """
    manager = get_tool_manager()
    return await manager.get_tool_schema(category, tool)


async def tools_dispatch(
    category: str,
    tool: str,
    params: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """Execute a tool by category and name.
    
    This is the main entry point for executing tools in the hierarchical
    tool system. Provide the category, tool name, and parameters.
    
    Args:
        category: Category containing the tool.
        tool: Name of the tool to execute.
        params: Parameters to pass to the tool (optional).
    
    Returns:
        Tool execution result.
    """
    manager = get_tool_manager()
    return await manager.dispatch(category, tool, params)


__all__ = [
    "HierarchicalToolManager",
    "ToolCategory",
    "get_tool_manager",
    "tools_list_categories",
    "tools_list_tools",
    "tools_get_schema",
    "tools_dispatch",
]
