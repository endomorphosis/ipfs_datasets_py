# src/mcp_server/tool_registry.py

import logging
from typing import Dict, Any, List, Optional, Union
from datetime import datetime, timezone
from abc import ABC, abstractmethod

from ipfs_datasets_py.mcp_server.tools.tool_wrapper import BaseMCPTool, wrap_function_as_tool
from ipfs_datasets_py.mcp_server.exceptions import (
    ToolExecutionError,
    ToolRegistrationError,
    ToolNotFoundError,
    ValidationError as MCPValidationError,
    ConfigurationError,
)


logger = logging.getLogger(__name__)

class ClaudeMCPTool(ABC):
    """
    Base class for Claude MCP (Model Context Protocol) Tools.
    This abstract base class provides a standardized interface for creating and managing
    tools that can be executed within the Claude MCP framework. It handles common
    functionality such as schema management, usage tracking, and execution patterns.

    Attributes:
        name (str): The unique identifier name for the tool.
        description (str): A human-readable description of what the tool does.
        input_schema (Dict[str, Any]): JSON schema defining the expected input parameters.
        category (str): The category classification for the tool (default: "general").
        tags (List[str]): List of tags for tool discovery and organization.
        version (str): Version string of the tool (default: "1.0.0").
        created_at (datetime): UTC timestamp when the tool instance was created.
        last_used (datetime): UTC timestamp of the most recent tool execution.
        usage_count (int): Counter tracking how many times the tool has been executed.

    Methods:
        execute(parameters: Dict[str, Any]) -> Dict[str, Any]:
            Abstract method that must be implemented by subclasses to define the
            core tool functionality. Executes the tool with the provided parameters.
        get_schema() -> Dict[str, Any]:
            Returns the complete tool schema including name, description, input schema,
            category, tags, and version information.
        run(**kwargs) -> Dict[str, Any]:
            Convenience method that accepts keyword arguments, updates usage statistics,
            and delegates to the execute method. Automatically increments usage_count
            and updates last_used timestamp.

    Example:
        >>> class MyTool(ClaudeMCPTool):
        ...     def __init__(self):
        ...         super().__init__()
        ...         self.name = "my_tool"
        ...         self.description = "Does something useful"
        ...     
        ...     async def execute(self, parameters):
        ...         return {"result": "success"}
        >>> tool = MyTool()
        >>> result = await tool.run(param1="value1")
    """
    def __init__(self):
        """
        Attributes initialized:
            name (str): The unique identifier name for the tool.
            description (str): A human-readable description of what the tool does.
            input_schema (Dict[str, Any]): JSON schema defining the expected input parameters.
            category (str): The category classification for the tool (default: "general").
            tags (List[str]): List of tags for tool discovery and organization.
            version (str): Version string of the tool (default: "1.0.0").
            created_at (datetime): UTC timestamp when the tool instance was created.
            last_used (datetime): UTC timestamp of the most recent tool execution.
            usage_count (int): Counter tracking how many times the tool has been executed.
        """
        self.name: str = ""
        self.description: str = ""
        self.input_schema: Dict[str, Any] = {}
        self.category: str = "general"
        self.tags: List[str] = []
        self.version: str = "1.0.0"
        self.created_at = datetime.now(tz=timezone.utc)
        self.last_used = None
        self.usage_count = 0
    
    @abstractmethod
    async def execute(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """Execute the tool with the provided parameters and return the result.

        This method serves as the main entry point for tool execution within the MCP (Model Context Protocol)
        framework. It processes the input parameters, performs the tool-specific operations, and returns
        the results in a standardized format.

        Args:
            parameters (Dict[str, Any]): A dictionary containing the input parameters required for tool
                execution. The structure and required keys depend on the specific tool implementation.
                Common parameter types may include:
                - Configuration settings
                - Input data or file paths  
                - Processing options and flags
                - Authentication credentials (if required)

        Returns:
            Dict[str, Any]: A dictionary containing the execution results and metadata. The return
                structure typically includes:
                - 'success': Boolean indicating if execution completed successfully
                - 'result': The main output data from the tool operation
                - 'error': Error message if execution failed (optional)
                - 'metadata': Additional information about the execution (optional)

        Raises:
            ValueError: If required parameters are missing or invalid
            RuntimeError: If tool execution fails due to runtime conditions
            NotImplementedError: If the method is not implemented by the subclass

        Note:
            This is an abstract method that must be implemented by concrete tool classes.
            The implementation should handle parameter validation, error handling, and
            ensure thread-safe execution if the tool will be used concurrently.

        Example:
            >>> tool = SomeTool()
            >>> params = {'input': 'data', 'option': 'value'}
            >>> result = await tool.execute(params)
            >>> print(result['success'])
            True
        """
        pass
    
    def get_schema(self) -> Dict[str, Any]:
        """Get the complete tool schema with all metadata.

        This method returns a comprehensive dictionary containing all the essential
        metadata and configuration information for the tool. The schema includes
        the tool's identification, description, input requirements, categorization,
        and versioning information.

        Returns:
            Dict[str, Any]: A dictionary containing the complete tool schema with the following keys:
                - name (str): The unique identifier/name of the tool
                - description (str): A human-readable description of what the tool does
                - input_schema (Dict): The JSON schema defining the expected input parameters
                - category (str): The functional category this tool belongs to
                - tags (List[str]): A list of tags for tool discovery and filtering
                - version (str): The current version of the tool

        Example:
            >>> tool = SomeTool()
            >>> schema = tool.get_schema()
            >>> print(schema['name'])
            'example_tool'
            >>> print(schema['input_schema'])
            {'type': 'object', 'properties': {...}}
        """
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
            "category": self.category,
            "tags": self.tags,
            "version": self.version
        }
    
    async def run(self, **kwargs) -> Dict[str, Any]:
        """Execute the tool with provided keyword arguments and update usage statistics.

        This method serves as the main entry point for tool execution, handling both
        the actual tool logic and internal bookkeeping. It increments the usage counter
        and records the timestamp of the current execution before delegating to the
        concrete implementation.

        Args:
            **kwargs: Arbitrary keyword arguments that will be passed to the tool's
                execute method. The specific arguments depend on the tool implementation
                and should be documented in the individual tool classes.

        Returns:
            Dict[str, Any]: A dictionary containing the results of the tool execution.
                The structure and content of this dictionary varies by tool type but
                typically includes status information, processed data, or error details.

        Raises:
            Any exceptions raised by the underlying execute() method will propagate
            up to the caller. Common exceptions may include validation errors,
            network timeouts, or tool-specific operational failures.

        Note:
            This method automatically tracks usage metrics including execution count
            and last execution timestamp. The timezone for timestamps is set to UTC
            for consistency across different deployment environments.

        Example:
            >>> tool = SomeTool()
            >>> result = await tool.run(input_data="example", format="json")
            >>> print(result)
            {'status': 'success', 'data': {...}}
        """
        self.usage_count += 1
        self.last_used = datetime.now(tz=timezone.utc)
        return await self.execute(kwargs)


class ToolRegistry:
    """
    This class provides a centralized registry for MCP (Model Context Protocol) tools,
    allowing registration, categorization, discovery, and execution of tools. It maintains
    tools organized by categories and tags, tracks usage statistics, and provides
    search capabilities.

    Attributes:
        _tools (Dict[str, ClaudeMCPTool]): Dictionary mapping tool names to tool instances
        _categories (Dict[str, List[str]]): Dictionary mapping category names to lists of tool names
        _tags (Dict[str, List[str]]): Dictionary mapping tag names to lists of tool names
        total_executions (int): Total number of tool executions across all tools

    Methods:
        register_tool(tool: ClaudeMCPTool) -> None:
            Register a tool with the registry, organizing it by category and tags.
        unregister_tool(tool_name: str) -> bool:
            Remove a tool from the registry and clean up category/tag references.
        get_tool(tool_name: str) -> Optional[ClaudeMCPTool]:
            Retrieve a specific tool by name.
        has_tool(tool_name: str) -> bool:
            Check if a tool is registered in the registry.
        get_all_tools() -> List[ClaudeMCPTool]:
            Get all registered tools as a list.
        list_tools() -> List[Dict[str, Any]]:
            Get schemas for all registered tools.
        get_tools_by_category(category: str) -> List[ClaudeMCPTool]:
            Retrieve all tools belonging to a specific category.
        get_tools_by_tag(tag: str) -> List[ClaudeMCPTool]:
            Retrieve all tools with a specific tag.
        get_categories() -> List[str]:
            Get all available tool categories.
        get_tags() -> List[str]:
            Get all available tool tags.
        execute_tool(tool_name: str, parameters: Dict[str, Any]) -> Dict[str, Any]:
            Execute a tool with given parameters and track execution count.
        get_tool_statistics() -> Dict[str, Any]:
            Get comprehensive usage statistics for all tools and registry.
        search_tools(query: str) -> List[ClaudeMCPTool]:
            Search for tools by name, description, or tags using a query string.
        validate_tool_parameters(tool_name: str, parameters: Dict[str, Any]) -> bool:
            Validate parameters against a tool's input schema.

    Example:
        registry = ToolRegistry()
        registry.register_tool(my_tool)
        result = await registry.execute_tool("my_tool", {"param": "value"})
    """
    def __init__(self):
        """Initialize the tool registry.

        This initializes an empty registry for managing Claude MCP tools with the following attributes:

        Attributes:
            _tools (Dict[str, ClaudeMCPTool]): Dictionary mapping tool names to their corresponding ClaudeMCPTool instances
            _categories (Dict[str, List[str]]): Dictionary mapping category names to lists of tool names in that category
            _tags (Dict[str, List[str]]): Dictionary mapping tag names to lists of tool names associated with that tag
            total_executions (int): Counter tracking the total number of tool executions across all registered tools
        """
        self._tools: Dict[str, ClaudeMCPTool] = {}
        self._categories: Dict[str, List[str]] = {}
        self._tags: Dict[str, List[str]] = {}
        self.total_executions = 0
        logger.info("Tool registry initialized")
    
    def register_tool(self, tool: Union[ClaudeMCPTool, BaseMCPTool]) -> None:
        """Register a tool with the registry.

        This method adds a ClaudeMCPTool instance to the registry, making it available
        for discovery and execution. The registration process includes:
        - Validating that the tool inherits from ClaudeMCPTool
        - Storing the tool in the main tools dictionary
        - Organizing the tool by category for efficient categorized lookups
        - Indexing the tool by its tags for tag-based searches
        - Logging the registration event for debugging and monitoring

        If a tool with the same name already exists, it will be overwritten with
        a warning logged to indicate the replacement.

        Args:
            tool (ClaudeMCPTool): The tool instance to register. Must be a subclass
                of ClaudeMCPTool and have valid name, category, and tags attributes.

        Returns:
            None

        Raises:
            ValueError: If the provided tool does not inherit from ClaudeMCPTool.

        Side Effects:
            - Updates the internal _tools dictionary
            - Updates the _categories mapping for tool organization
            - Updates the _tags mapping for tag-based tool discovery
            - Logs registration information and any overwrites

        Example:
            >>> registry = ToolRegistry()
            >>> my_tool = MyCustomTool()
            >>> registry.register_tool(my_tool)
            # Tool is now available for lookup and execution
        """
        if not isinstance(tool, (ClaudeMCPTool, BaseMCPTool)):
            raise ValueError("Tool must inherit from ClaudeMCPTool or BaseMCPTool")
        
        if tool.name in self._tools:
            logger.warning(f"Tool '{tool.name}' already registered, overwriting")
        
        self._tools[tool.name] = tool
        
        # Update categories
        if tool.category not in self._categories:
            self._categories[tool.category] = []
        if tool.name not in self._categories[tool.category]:
            self._categories[tool.category].append(tool.name)
        
        # Update tags
        for tag in tool.tags:
            if tag not in self._tags:
                self._tags[tag] = []
            if tool.name not in self._tags[tag]:
                self._tags[tag].append(tool.name)
        
        logger.info(f"Registered tool: {tool.name} (category: {tool.category})")
    
    def unregister_tool(self, tool_name: str) -> bool:
        """Unregister a tool from the registry and clean up all associated references.

        This method removes a tool from the main tool registry and performs comprehensive
        cleanup by removing the tool from category and tag mappings. Empty categories and
        tags are automatically removed to maintain registry cleanliness.

        Args:
            tool_name (str): The unique name/identifier of the tool to unregister.
                            Must match exactly with a previously registered tool name.
        Returns:
            bool: True if the tool was successfully unregistered, False if the tool
                  was not found in the registry.

        Side Effects:
            - Removes the tool from the main tools dictionary
            - Removes the tool from its associated category list
            - Removes empty categories from the category registry
            - Removes the tool from all associated tag lists
            - Removes empty tags from the tag registry
            - Logs an info message upon successful unregistration

        Example:
            >>> registry = ToolRegistry()
            >>> registry.register_tool(some_tool)
            >>> success = registry.unregister_tool("my_tool")
            >>> print(success)  # True if tool existed, False otherwise

        Note:
            This operation is irreversible. Once a tool is unregistered, it must be
            re-registered to be available again in the registry.
        """
        if tool_name not in self._tools:
            return False
        
        tool = self._tools[tool_name]
        
        # Remove from categories
        if tool.category in self._categories:
            if tool_name in self._categories[tool.category]:
                self._categories[tool.category].remove(tool_name)
            if not self._categories[tool.category]:
                del self._categories[tool.category]
        
        # Remove from tags
        for tag in tool.tags:
            if tag in self._tags and tool_name in self._tags[tag]:
                self._tags[tag].remove(tool_name)
                if not self._tags[tag]:
                    del self._tags[tag]
        
        del self._tools[tool_name]
        logger.info(f"Unregistered tool: {tool_name}")
        return True
    
    def get_tool(self, tool_name: str) -> Optional[ClaudeMCPTool]:
        """Retrieve a tool instance by its unique name identifier.

        This method provides access to a specific tool registered in the registry by its
        unique name. It performs a simple lookup operation and returns the tool instance
        if found, or None if no tool with the given name exists.

        Args:
            tool_name (str): The unique name/identifier of the tool to retrieve.
                    This should match exactly with the name used during tool
                    registration (case-sensitive).

        Returns:
            Optional[ClaudeMCPTool]: The tool instance if found, None otherwise.
                        The returned tool can be used to execute operations,
                        access its schema, or inspect its metadata.

        Example:
            >>> registry = ToolRegistry()
            >>> registry.register_tool(my_tool)  # my_tool.name = "example_tool"
            >>> tool = registry.get_tool("example_tool")
            >>> if tool:
            ...     result = await tool.execute({"param": "value"})
            >>> else:
            ...     print("Tool not found")

        Note:
            This method does not raise exceptions for missing tools. Use has_tool()
            to check for tool existence before retrieval, or handle the None return
            value appropriately in your code.
        """
        return self._tools.get(tool_name)
    
    def has_tool(self, tool_name: str) -> bool:
        """Check if a tool with the given name is registered in the registry.
        
        This method performs a quick membership test to determine whether a tool
        with the specified name exists in the registry. It's useful for validation
        before attempting tool retrieval or execution operations.
        
        Args:
            tool_name (str): The unique name/identifier of the tool to check.
                    Case-sensitive and must match exactly with the registered name.
        
        Returns:
            bool: True if the tool is registered, False otherwise.
        
        Example:
            >>> registry = ToolRegistry()
            >>> registry.register_tool(my_tool)
            >>> if registry.has_tool("my_tool"):
            ...     tool = registry.get_tool("my_tool")
            ...     result = await tool.execute(params)
        
        Note:
            This is a fast O(1) lookup operation that checks tool name membership
            in the internal tools dictionary.
        """
        return tool_name in self._tools
    
    def get_all_tools(self) -> List[ClaudeMCPTool]:
        """Retrieve a complete list of all tools currently registered in the registry.
        
        This method returns all tool instances that have been registered, regardless
        of their category, tags, or other metadata. The tools are returned as a list
        in no guaranteed order.
        
        Returns:
            List[ClaudeMCPTool]: A list containing all registered tool instances.
                        Returns an empty list if no tools are registered. The list
                        is a snapshot of current registrations and modifications to
                        it won't affect the registry.
        
        Example:
            >>> registry = ToolRegistry()
            >>> registry.register_tool(tool1)
            >>> registry.register_tool(tool2)
            >>> all_tools = registry.get_all_tools()
            >>> print(f"Total tools: {len(all_tools)}")
            Total tools: 2
            >>> for tool in all_tools:
            ...     print(f"- {tool.name}")
        
        Note:
            - This returns the actual tool instances, not just their names or schemas
            - For large registries, consider using get_tools_by_category() or
              get_tools_by_tag() to retrieve specific subsets
            - The returned list is a new instance; modifying it won't affect the registry
        """
        return list(self._tools.values())
    
    def list_tools(self) -> List[Dict[str, Any]]:
        """List all registered tools with their complete MCP schema definitions.
        
        This method provides a comprehensive overview of all registered tools by
        returning their full MCP schema definitions. Each schema includes the tool's
        name, description, parameters, and any other metadata defined in the tool
        specification. This is particularly useful for MCP protocol communication
        and tool discovery interfaces.
        
        Returns:
            List[Dict[str, Any]]: A list of dictionaries, where each dictionary
                        contains the complete MCP schema for a registered tool.
                        Returns an empty list if no tools are registered. Schemas
                        follow the MCP protocol specification format.
        
        Example:
            >>> registry = ToolRegistry()
            >>> registry.register_tool(my_tool)
            >>> schemas = registry.list_tools()
            >>> for schema in schemas:
            ...     print(f"Tool: {schema['name']}")
            ...     print(f"Description: {schema['description']}")
            ...     print(f"Parameters: {schema.get('inputSchema', {})}")
        
        Note:
            - Each tool's get_schema() method is called to generate the schema
            - Schemas are regenerated on each call (not cached)
            - Schema format follows MCP protocol specification
            - Suitable for JSON serialization and transmission over MCP protocol
        """
        return [tool.get_schema() for tool in self._tools.values()]
    
    def get_tools_by_category(self, category: str) -> List[ClaudeMCPTool]:
        """Retrieve all tools that belong to a specific category.
        
        This method filters the registered tools by category, returning only those
        tools that were assigned to the specified category during registration.
        Categories are used to organize tools by their functional domain (e.g.,
        "dataset_tools", "ipfs_tools", "analysis_tools").
        
        Args:
            category (str): The category name to filter by. Must match exactly
                    with category names assigned during tool registration
                    (case-sensitive).
        
        Returns:
            List[ClaudeMCPTool]: A list of tool instances in the specified category.
                        Returns an empty list if the category doesn't exist or has
                        no tools registered. Tools are returned in registration order.
        
        Example:
            >>> registry = ToolRegistry()
            >>> registry.register_tool(dataset_tool)  # category="dataset_tools"
            >>> registry.register_tool(ipfs_tool)     # category="ipfs_tools"
            >>> dataset_tools = registry.get_tools_by_category("dataset_tools")
            >>> print(f"Found {len(dataset_tools)} dataset tools")
            >>> for tool in dataset_tools:
            ...     print(f"- {tool.name}")
        
        Note:
            - Category filtering is case-sensitive
            - Returns actual tool instances, not copies
            - Invalid/non-existent categories return empty list (no exception raised)
            - Tools can only belong to one category at a time
        """
        tool_names = self._categories.get(category, [])
        return [self._tools[name] for name in tool_names if name in self._tools]
    
    def get_tools_by_tag(self, tag: str) -> List[ClaudeMCPTool]:
        """Retrieve all tools that have been assigned a specific tag.
        
        This method filters the registered tools by tag, returning all tools that
        were tagged with the specified label during registration. Tags provide a
        flexible cross-cutting classification system (e.g., "async", "experimental",
        "production-ready") that complements the hierarchical category system.
        
        Args:
            tag (str): The tag name to filter by. Must match exactly with tag
                    names assigned during tool registration (case-sensitive).
        
        Returns:
            List[ClaudeMCPTool]: A list of tool instances with the specified tag.
                        Returns an empty list if the tag doesn't exist or no tools
                        have been tagged with it. Tools are returned in the order
                        they were tagged.
        
        Example:
            >>> registry = ToolRegistry()
            >>> registry.register_tool(async_tool)     # tags=["async", "production"]
            >>> registry.register_tool(sync_tool)      # tags=["sync", "production"]
            >>> prod_tools = registry.get_tools_by_tag("production")
            >>> print(f"Found {len(prod_tools)} production tools")
            >>> async_tools = registry.get_tools_by_tag("async")
            >>> print(f"Found {len(async_tools)} async tools")
        
        Note:
            - Tag filtering is case-sensitive
            - Returns actual tool instances, not copies
            - Invalid/non-existent tags return empty list (no exception raised)
            - Unlike categories, tools can have multiple tags
            - Useful for cross-cutting concerns (async/sync, stable/experimental, etc.)
        """
        tool_names = self._tags.get(tag, [])
        return [self._tools[name] for name in tool_names if name in self._tools]
    
    def get_categories(self) -> List[str]:
        """Retrieve a list of all unique categories currently in use by registered tools.
        
        This method returns the complete set of category names that have been assigned
        to at least one registered tool. Categories provide a hierarchical organization
        system for tools, grouping them by functional domain or purpose.
        
        Returns:
            List[str]: A list of all category names that have registered tools.
                        Returns an empty list if no tools are registered or no
                        categories have been assigned. The list order is not guaranteed.
        
        Example:
            >>> registry = ToolRegistry()
            >>> registry.register_tool(dataset_tool)  # category="dataset_tools"
            >>> registry.register_tool(ipfs_tool)     # category="ipfs_tools"
            >>> registry.register_tool(another_ipfs)  # category="ipfs_tools"
            >>> categories = registry.get_categories()
            >>> print(categories)
            ['dataset_tools', 'ipfs_tools']
            >>> print(f"Total categories: {len(categories)}")
            Total categories: 2
        
        Note:
            - Only categories with at least one registered tool are returned
            - Categories with all tools unregistered are automatically removed
            - The returned list is a snapshot; modifications don't affect the registry
            - Useful for building category navigation or tool discovery interfaces
        """
        return list(self._categories.keys())
    
    def get_tags(self) -> List[str]:
        """Retrieve a list of all unique tags currently assigned to registered tools.
        
        This method returns the complete set of tag names that have been assigned
        to at least one registered tool. Tags provide a flexible, cross-cutting
        classification system that complements the hierarchical category structure,
        allowing tools to be labeled with multiple attributes or characteristics.
        
        Returns:
            List[str]: A list of all tag names that have been assigned to registered
                        tools. Returns an empty list if no tools are registered or no
                        tags have been assigned. The list order is not guaranteed.
        
        Example:
            >>> registry = ToolRegistry()
            >>> registry.register_tool(async_tool)  # tags=["async", "experimental"]
            >>> registry.register_tool(sync_tool)   # tags=["sync", "production"]
            >>> registry.register_tool(beta_tool)   # tags=["async", "production"]
            >>> tags = registry.get_tags()
            >>> print(sorted(tags))
            ['async', 'experimental', 'production', 'sync']
            >>> print(f"Total unique tags: {len(tags)}")
            Total unique tags: 4
        
        Note:
            - Only tags assigned to at least one registered tool are returned
            - Tags with all associated tools unregistered are automatically removed
            - The returned list is a snapshot; modifications don't affect the registry
            - Useful for building tag-based filtering or tool discovery interfaces
            - Unlike categories, tools can have multiple tags simultaneously
        """
        return list(self._tags.keys())
    
    async def execute_tool(self, tool_name: str, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """Execute a tool with the given parameters and track execution statistics.

        This method provides a centralized execution interface for registered tools,
        handling parameter validation, execution tracking, and error management.
        It serves as the primary entry point for tool execution within the MCP framework.

        Args:
            tool_name (str): The unique identifier of the tool to execute. Must match
            exactly with a registered tool name in the registry.
            parameters (Dict[str, Any]): A dictionary containing the input parameters
            required for tool execution. The structure and required keys depend
            on the specific tool's input schema.

        Returns:
            Dict[str, Any]: A dictionary containing the execution results. The structure
            varies by tool but typically includes:
            - 'success': Boolean indicating execution status
            - 'result': The main output data from the tool
            - 'error': Error message if execution failed (optional)
            - 'metadata': Additional execution information (optional)

        Raises:
            ValueError: If the specified tool_name is not found in the registry.
            Exception: Any tool-specific exceptions raised during execution are
            propagated to the caller with detailed error logging.

        Side Effects:
            - Increments the registry's total_executions counter
            - Updates the tool's individual usage statistics
            - Logs execution attempts and results for monitoring

        Example:
            >>> registry = ToolRegistry()
            >>> result = await registry.execute_tool("my_tool", {"input": "data"})
            >>> print(result['success'])
            True
        """
        if tool_name not in self._tools:
            from ipfs_datasets_py.mcp_server.exceptions import ToolNotFoundError
            raise ToolNotFoundError(tool_name)
        
        tool = self._tools[tool_name]
        self.total_executions += 1
        
        try:
            result = await tool.execute(parameters)
            logger.debug(f"Tool '{tool_name}' executed successfully")
            return result
        except ToolExecutionError:
            # Re-raise custom exceptions without wrapping
            raise
        except Exception as e:
            logger.error(f"Tool '{tool_name}' execution failed: {e}", exc_info=True)
            raise ToolExecutionError(tool_name, e)
    
    def get_tool_statistics(self) -> Dict[str, Any]:
        """Get comprehensive usage statistics for all tools and registry.

        This method provides detailed analytics and metrics about tool usage patterns,
        registry state, and operational statistics. It compiles information from all
        registered tools to give a complete picture of system utilization.

        Returns:
            Dict[str, Any]: A comprehensive statistics dictionary containing:
            - total_tools (int): Total number of registered tools in the registry
            - total_executions (int): Aggregate count of all tool executions across the registry
            - categories (Dict[str, int]): Mapping of category names to tool counts in each category
            - tags (Dict[str, int]): Mapping of tag names to tool counts associated with each tag
            - tool_usage (Dict[str, Dict]): Detailed per-tool statistics including:
                - usage_count (int): Number of times this specific tool has been executed
                - last_used (str | None): ISO formatted timestamp of last execution, None if never used
                - category (str): Category classification of the tool
                - created_at (str): ISO formatted timestamp when tool was registered
                - version (str): Current version of the tool

        Example:
            >>> registry = ToolRegistry()
            >>> # ... register some tools and execute them ...
            >>> stats = registry.get_tool_statistics()
            >>> print(f"Total tools: {stats['total_tools']}")
            >>> print(f"Most used tool: {max(stats['tool_usage'].items(), key=lambda x: x[1]['usage_count'])}")
            >>> print(f"Categories: {list(stats['categories'].keys())}")

        Note:
            - Timestamps are in UTC and ISO 8601 format for consistency
            - Never-used tools will have last_used as None
            - Empty categories or tags are excluded from the counts
            - Statistics are computed in real-time and reflect current registry state
        """
        stats = {
            "total_tools": len(self._tools),
            "total_executions": self.total_executions,
            "categories": {cat: len(tools) for cat, tools in self._categories.items()},
            "tags": {tag: len(tools) for tag, tools in self._tags.items()},
            "tool_usage": {
                name: {
                    "usage_count": tool.usage_count,
                    "last_used": tool.last_used.isoformat() if tool.last_used else None,
                    "category": tool.category
                }
                for name, tool in self._tools.items()
            }
        }
        return stats
    
    def search_tools(self, query: str) -> List[ClaudeMCPTool]:
        """Search for tools by name, description, or tags using a flexible query string.

        This method performs a comprehensive search across all registered tools, matching
        the query against tool names, descriptions, and associated tags. The search is
        case-insensitive and uses substring matching to find relevant tools.

        Args:
            query (str): The search query string. Can match against:
            - Tool names (partial or full matches)
            - Tool descriptions (searches within description text)
            - Tags (matches any tag associated with the tool)
            Empty or whitespace-only queries will return an empty list.

        Returns:
            List[ClaudeMCPTool]: A list of tools that match the search criteria.
            Tools are returned in the order they are found in the registry.
            If no matches are found, returns an empty list.

        Example:
            >>> registry = ToolRegistry()
            >>> # Search for embedding-related tools
            >>> embedding_tools = registry.search_tools("embedding")
            >>> # Search for tools in a specific category
            >>> storage_tools = registry.search_tools("storage")
            >>> # Search by partial name
            >>> batch_tools = registry.search_tools("batch")

        Note:
            - The search is performed across all registered tools each time
            - Search is case-insensitive for better usability
            - Uses substring matching, so partial matches will be returned
            - Performance scales with the number of registered tools
        """
        query_lower = query.lower()
        matching_tools = []
        
        for tool in self._tools.values():
            if (query_lower in tool.name.lower() or 
                query_lower in tool.description.lower() or
                any(query_lower in tag.lower() for tag in tool.tags)):
                matching_tools.append(tool)
        
        return matching_tools
    
    def validate_tool_parameters(self, tool_name: str, parameters: Dict[str, Any]) -> bool:
        """Validate parameters against a tool's input schema with comprehensive validation.

        This method performs thorough validation of input parameters against the specified
        tool's input schema definition. It validates both required parameters and parameter
        types according to JSON schema standards, providing detailed feedback on validation
        failures.

        Args:
            tool_name (str): The unique identifier of the tool whose schema should be
            used for validation. Must match exactly with a registered tool name.
            parameters (Dict[str, Any]): A dictionary containing the parameters to validate.
            The structure and content will be checked against the tool's input schema.

        Returns:
            bool: True if all parameters pass validation according to the tool's schema,
            False if the tool is not found or if any validation checks fail.

        Validation Checks Performed:
            - Tool existence: Verifies the specified tool is registered
            - Required parameters: Ensures all required fields are present
            - Parameter types: Validates parameter types match schema definitions (if specified)
            - Additional properties: Checks if extra parameters are allowed (if schema specifies)

        Example:
            >>> registry = ToolRegistry()
            >>> # Tool with schema requiring 'input' parameter of type string
            >>> params = {"input": "test data", "optional_param": 42}
            >>> is_valid = registry.validate_tool_parameters("my_tool", params)
            >>> print(is_valid)  # True if validation passes

        Note:
            - Validation failures are logged for debugging purposes
            - Returns False for non-existent tools rather than raising exceptions
        """
        tool = self.get_tool(tool_name)
        if not tool:
            return False
        
        # TODO Basic validation - could be extended with JSON schema validation
        schema = tool.input_schema
        if "required" in schema:
            for required_param in schema["required"]:
                if required_param not in parameters:
                    return False
        
        return True


def _register_embedding_tools(registry: ToolRegistry, embedding_service: Optional[Any] = None) -> None:
    """Register embedding tools with the registry."""
    try:
        from ipfs_datasets_py.mcp_server.tools.embedding_tools.embedding_tools import (
            BatchEmbeddingTool,
            EmbeddingGenerationTool,
            MultimodalEmbeddingTool,
        )

        registry.register_tool(EmbeddingGenerationTool(embedding_service))
        registry.register_tool(BatchEmbeddingTool(embedding_service))
        registry.register_tool(MultimodalEmbeddingTool(embedding_service))
    except ToolRegistrationError as e:
        logger.warning(f"Tool registration error for embedding tools: {e}")
    except ConfigurationError as e:
        logger.warning(f"Configuration error for embedding tools: {e}")
    except Exception as e:
        logger.warning(f"Unexpected error registering embedding tools: {e}", exc_info=True)

        # Compatibility fallback: register function-based embedding tools.
        try:
            from ipfs_datasets_py.mcp_server.tools.embedding_tools.embedding_generation import (
                generate_batch_embeddings,
                generate_embedding,
            )

            registry.register_tool(
                wrap_function_as_tool(generate_embedding, "generate_embedding", "embedding")
            )
            registry.register_tool(
                wrap_function_as_tool(generate_batch_embeddings, "generate_batch_embeddings", "embedding")
            )
        except ToolRegistrationError as e2:
            logger.warning(f"Tool registration error for embedding fallbacks: {e2}")
        except Exception as e2:
            logger.warning(f"Unexpected error registering embedding fallbacks: {e2}", exc_info=True)


def _register_search_tools(registry: ToolRegistry, embedding_service: Optional[Any] = None) -> None:
    """Register search tools with the registry."""
    try:
        from ipfs_datasets_py.mcp_server.tools.search_tools.search_tools import (
            FacetedSearchTool,
            SemanticSearchTool,
            SimilaritySearchTool,
        )

        registry.register_tool(SemanticSearchTool(embedding_service))
        registry.register_tool(SimilaritySearchTool(embedding_service))
        registry.register_tool(FacetedSearchTool(embedding_service))
    except ToolRegistrationError as e:
        logger.warning(f"Tool registration error for search tools: {e}")
    except ConfigurationError as e:
        logger.warning(f"Configuration error for search tools: {e}")
    except Exception as e:
        logger.warning(f"Unexpected error registering search tools: {e}", exc_info=True)


def _register_analysis_tools(registry: ToolRegistry, embedding_service: Optional[Any] = None) -> None:
    """Register analysis tools with the registry."""
    try:
        from ipfs_datasets_py.mcp_server.tools.analysis_tools.analysis_tools import (
            cluster_analysis,
            dimensionality_reduction,
            quality_assessment,
        )

        registry.register_tool(wrap_function_as_tool(cluster_analysis, "cluster_analysis", "analysis"))
        registry.register_tool(wrap_function_as_tool(quality_assessment, "quality_assessment", "analysis"))
        registry.register_tool(wrap_function_as_tool(dimensionality_reduction, "dimensionality_reduction", "analysis"))
    except ToolRegistrationError as e:
        logger.warning(f"Tool registration error for analysis tools: {e}")
    except Exception as e:
        logger.warning(f"Unexpected error registering analysis tools: {e}", exc_info=True)


def _register_storage_tools(registry: ToolRegistry, embedding_service: Optional[Any] = None) -> None:
    """Register storage tools with the registry."""
    try:
        from ipfs_datasets_py.mcp_server.tools.storage_tools.storage_tools import CollectionManagementTool, StorageManagementTool

        registry.register_tool(StorageManagementTool(embedding_service))
        registry.register_tool(CollectionManagementTool(embedding_service))
    except ToolRegistrationError as e:
        logger.warning(f"Tool registration error for storage tools: {e}")
    except ConfigurationError as e:
        logger.warning(f"Configuration error for storage tools: {e}")
    except Exception as e:
        logger.warning(f"Unexpected error registering storage tools: {e}", exc_info=True)


def _register_data_processing_tools(registry: ToolRegistry, embedding_service: Optional[Any] = None) -> None:
    """Register data processing tools with the registry."""
    if embedding_service is not None:
        try:
            from ipfs_datasets_py.mcp_server.tools.data_processing_tools.data_processing_tools import ChunkingTool, DatasetLoadingTool, ParquetToCarTool

            registry.register_tool(ChunkingTool(embedding_service))
            registry.register_tool(DatasetLoadingTool(embedding_service))
            registry.register_tool(ParquetToCarTool(embedding_service))
        except ToolRegistrationError as e:
            logger.warning(f"Tool registration error for data processing tools: {e}")
        except ConfigurationError as e:
            logger.warning(f"Configuration error for data processing tools: {e}")
        except Exception as e:
            logger.warning(f"Unexpected error registering data processing tools: {e}", exc_info=True)
    else:
        logger.info("Skipping data processing tools registration (no embedding service provided)")


def _register_auth_tools(registry: ToolRegistry, embedding_service: Optional[Any] = None) -> None:
    """Register auth tools with the registry."""
    try:
        from ipfs_datasets_py.mcp_server.tools.auth_tools.auth_tools import AuthenticationTool, TokenValidationTool, UserInfoTool

        registry.register_tool(AuthenticationTool(embedding_service))
        registry.register_tool(UserInfoTool(embedding_service))
        registry.register_tool(TokenValidationTool(embedding_service))
    except ToolRegistrationError as e:
        logger.warning(f"Tool registration error for authentication tools: {e}")
    except ConfigurationError as e:
        logger.warning(f"Configuration error for authentication tools: {e}")
    except Exception as e:
        logger.warning(f"Unexpected error registering authentication tools: {e}", exc_info=True)


def _register_admin_tools(registry: ToolRegistry, embedding_service: Optional[Any] = None) -> None:
    """Register admin tools with the registry."""
    try:
        from ipfs_datasets_py.mcp_server.tools.admin_tools.admin_tools import EndpointManagementTool, SystemConfigurationTool, UserManagementTool

        registry.register_tool(EndpointManagementTool(embedding_service))
        registry.register_tool(UserManagementTool(embedding_service))
        registry.register_tool(SystemConfigurationTool(embedding_service))
    except ToolRegistrationError as e:
        logger.warning(f"Tool registration error for admin tools: {e}")
    except ConfigurationError as e:
        logger.warning(f"Configuration error for admin tools: {e}")
    except Exception as e:
        logger.warning(f"Unexpected error registering admin tools: {e}", exc_info=True)


def _register_cache_tools(registry: ToolRegistry, embedding_service: Optional[Any] = None) -> None:
    """Register cache tools with the registry."""
    try:
        from ipfs_datasets_py.mcp_server.tools.cache_tools.cache_tools import CacheManagementTool, CacheMonitoringTool, CacheStatsTool

        registry.register_tool(CacheStatsTool(embedding_service))
        registry.register_tool(CacheManagementTool(embedding_service))
        registry.register_tool(CacheMonitoringTool(embedding_service))
    except ToolRegistrationError as e:
        logger.warning(f"Tool registration error for cache tools: {e}")
    except ConfigurationError as e:
        logger.warning(f"Configuration error for cache tools: {e}")
    except Exception as e:
        logger.warning(f"Unexpected error registering cache tools: {e}", exc_info=True)


def _register_monitoring_tools_group(registry: ToolRegistry, embedding_service: Optional[Any] = None) -> None:
    """Register monitoring tools with the registry."""
    try:
        from ipfs_datasets_py.mcp_server.tools.monitoring_tools.monitoring_tools import AlertManagementTool, HealthCheckTool, MetricsCollectionTool, SystemMonitoringTool

        registry.register_tool(HealthCheckTool(embedding_service))
        registry.register_tool(MetricsCollectionTool(embedding_service))
        registry.register_tool(SystemMonitoringTool(embedding_service))
        registry.register_tool(AlertManagementTool(embedding_service))
    except ToolRegistrationError as e:
        logger.warning(f"Tool registration error for monitoring tools: {e}")
    except ConfigurationError as e:
        logger.warning(f"Configuration error for monitoring tools: {e}")
    except Exception as e:
        logger.warning(f"Unexpected error registering monitoring tools: {e}", exc_info=True)


def _register_background_task_tools(registry: ToolRegistry, embedding_service: Optional[Any] = None) -> None:
    """Register background task tools with the registry."""
    try:
        from ipfs_datasets_py.mcp_server.tools.background_task_tools.background_task_tools import BackgroundTaskManagementTool, BackgroundTaskStatusTool, TaskQueueManagementTool

        registry.register_tool(BackgroundTaskStatusTool(embedding_service))
        registry.register_tool(BackgroundTaskManagementTool(embedding_service))
        registry.register_tool(TaskQueueManagementTool(embedding_service))
    except ToolRegistrationError as e:
        logger.warning(f"Tool registration error for background task tools: {e}")
    except ConfigurationError as e:
        logger.warning(f"Configuration error for background task tools: {e}")
    except Exception as e:
        logger.warning(f"Unexpected error registering background task tools: {e}", exc_info=True)


def _register_rate_limiting_tools(registry: ToolRegistry, embedding_service: Optional[Any] = None) -> None:
    """Register rate limiting tools with the registry."""
    try:
        from ipfs_datasets_py.mcp_server.tools.rate_limiting_tools.rate_limiting_tools import RateLimitConfigurationTool, RateLimitManagementTool, RateLimitMonitoringTool

        registry.register_tool(RateLimitConfigurationTool(embedding_service))
        registry.register_tool(RateLimitMonitoringTool(embedding_service))
        registry.register_tool(RateLimitManagementTool(embedding_service))
    except ToolRegistrationError as e:
        logger.warning(f"Tool registration error for rate limiting tools: {e}")
    except ConfigurationError as e:
        logger.warning(f"Configuration error for rate limiting tools: {e}")
    except Exception as e:
        logger.warning(f"Unexpected error registering rate limiting tools: {e}", exc_info=True)


def _register_index_management_tools(registry: ToolRegistry, embedding_service: Optional[Any] = None) -> None:
    """Register index management tools with the registry."""
    try:
        from ipfs_datasets_py.mcp_server.tools.index_management_tools.index_management_tools import IndexLoadingTool, IndexStatusTool, ShardManagementTool

        registry.register_tool(IndexLoadingTool(embedding_service))
        registry.register_tool(ShardManagementTool(embedding_service))
        registry.register_tool(IndexStatusTool(embedding_service))
    except ToolRegistrationError as e:
        logger.warning(f"Tool registration error for index management tools: {e}")
    except ConfigurationError as e:
        logger.warning(f"Configuration error for index management tools: {e}")
    except Exception as e:
        logger.warning(f"Unexpected error registering index management tools: {e}", exc_info=True)


def _register_sparse_embedding_tools(registry: ToolRegistry, embedding_service: Optional[Any] = None) -> None:
    """Register sparse embedding tools with the registry."""
    try:
        from ipfs_datasets_py.mcp_server.tools.sparse_embedding_tools.sparse_embedding_tools import SparseEmbeddingGenerationTool, SparseIndexingTool, SparseSearchTool

        registry.register_tool(SparseEmbeddingGenerationTool(embedding_service))
        registry.register_tool(SparseIndexingTool(embedding_service))
        registry.register_tool(SparseSearchTool(embedding_service))
    except ToolRegistrationError as e:
        logger.warning(f"Tool registration error for sparse embedding tools: {e}")
    except ConfigurationError as e:
        logger.warning(f"Configuration error for sparse embedding tools: {e}")
    except Exception as e:
        logger.warning(f"Unexpected error registering sparse embedding tools: {e}", exc_info=True)


def _register_ipfs_cluster_tools(registry: ToolRegistry, embedding_service: Optional[Any] = None) -> None:
    """Register IPFS cluster tools with the registry."""
    try:
        from ipfs_datasets_py.mcp_server.tools.ipfs_cluster_tools.enhanced_ipfs_cluster_tools import IPFSClusterManagementTool, IPFSPinningTool, StorachaIntegrationTool

        registry.register_tool(IPFSClusterManagementTool(embedding_service))
        registry.register_tool(StorachaIntegrationTool(embedding_service))
        registry.register_tool(IPFSPinningTool(embedding_service))
    except ToolRegistrationError as e:
        logger.warning(f"Tool registration error for IPFS cluster tools: {e}")
    except ConfigurationError as e:
        logger.warning(f"Configuration error for IPFS cluster tools: {e}")
    except Exception as e:
        logger.warning(f"Unexpected error registering IPFS cluster tools: {e}", exc_info=True)


def _register_session_tools(registry: ToolRegistry, embedding_service: Optional[Any] = None) -> None:
    """Register session tools with the registry."""
    try:
        from ipfs_datasets_py.mcp_server.tools.session_tools.session_tools import SessionCleanupTool, SessionCreationTool, SessionMonitoringTool

        registry.register_tool(SessionCreationTool(embedding_service))
        registry.register_tool(SessionMonitoringTool(embedding_service))
        registry.register_tool(SessionCleanupTool(embedding_service))
    except ToolRegistrationError as e:
        logger.warning(f"Tool registration error for session management tools: {e}")
    except ConfigurationError as e:
        logger.warning(f"Configuration error for session management tools: {e}")
    except Exception as e:
        logger.warning(f"Unexpected error registering session management tools: {e}", exc_info=True)


def _register_embedding_generation_tools(registry: ToolRegistry) -> None:
    """Register embedding generation tools with the registry."""
    try:
        from ipfs_datasets_py.mcp_server.tools.embedding_tools.embedding_generation import (
            generate_embedding,
            generate_batch_embeddings,
        )

        registry.register_tool(wrap_function_as_tool(generate_embedding, "create_embeddings", "embedding"))
        registry.register_tool(wrap_function_as_tool(generate_batch_embeddings, "batch_create_embeddings", "embedding"))
    except ToolRegistrationError as e:
        logger.warning(f"Tool registration error for create embeddings tools: {e}")
    except Exception as e:
        logger.warning(f"Unexpected error registering create embeddings tools: {e}", exc_info=True)


def _register_shard_embedding_tools(registry: ToolRegistry) -> None:
    """Register shard embedding tools with the registry."""
    try:
        from ipfs_datasets_py.mcp_server.tools.embedding_tools.shard_embeddings_tool import merge_shards_tool, shard_embeddings_tool, shard_info_tool

        registry.register_tool(wrap_function_as_tool(shard_embeddings_tool, "shard_embeddings", "processing"))
        registry.register_tool(wrap_function_as_tool(merge_shards_tool, "merge_shards", "processing"))
        registry.register_tool(wrap_function_as_tool(shard_info_tool, "shard_info", "analysis"))
    except ToolRegistrationError as e:
        logger.warning(f"Tool registration error for shard embeddings tools: {e}")
    except Exception as e:
        logger.warning(f"Unexpected error registering shard embeddings tools: {e}", exc_info=True)


def _register_vector_store_tools(registry: ToolRegistry) -> None:
    """Register vector store tools with the registry."""
    try:
        from ipfs_datasets_py.mcp_server.tools.vector_store_tools.vector_store_tools import (
            add_embeddings_to_store_tool,
            create_vector_store_tool,
            delete_from_vector_store_tool,
            get_vector_store_stats_tool,
            optimize_vector_store_tool,
            search_vector_store_tool,
        )

        registry.register_tool(wrap_function_as_tool(create_vector_store_tool, "create_vector_store", "storage"))
        registry.register_tool(wrap_function_as_tool(add_embeddings_to_store_tool, "add_embeddings_to_store", "storage"))
        registry.register_tool(wrap_function_as_tool(search_vector_store_tool, "search_vector_store", "search"))
        registry.register_tool(wrap_function_as_tool(get_vector_store_stats_tool, "get_vector_store_stats", "analysis"))
        registry.register_tool(wrap_function_as_tool(delete_from_vector_store_tool, "delete_from_vector_store", "storage"))
        registry.register_tool(wrap_function_as_tool(optimize_vector_store_tool, "optimize_vector_store", "optimization"))
    except Exception as e:
        logger.warning(f"Could not register vector store tools: {e}")


def _register_workflow_tools(registry: ToolRegistry) -> None:
    """Register workflow tools with the registry."""
    try:
        from ipfs_datasets_py.mcp_server.tools.workflow_tools.workflow_tools import (
            create_embedding_pipeline_tool,
            execute_workflow_tool,
            get_workflow_status_tool,
            list_workflows_tool,
        )

        registry.register_tool(wrap_function_as_tool(execute_workflow_tool, "execute_workflow", "orchestration"))
        registry.register_tool(wrap_function_as_tool(create_embedding_pipeline_tool, "create_embedding_pipeline", "orchestration"))
        registry.register_tool(wrap_function_as_tool(get_workflow_status_tool, "get_workflow_status", "monitoring"))
        registry.register_tool(wrap_function_as_tool(list_workflows_tool, "list_workflows", "monitoring"))
    except Exception as e:
        logger.warning(f"Could not register workflow orchestration tools: {e}")


def initialize_laion_tools(registry: Optional[ToolRegistry] = None, embedding_service: Optional[Any] = None) -> Optional[List[Any]]:
    """Initialize and register all LAION embedding tools with the tool registry.

    This function performs comprehensive initialization of all available tools in the LAION
    embedding system. It handles graceful registration of multiple tool categories, with
    robust error handling to ensure partial functionality even if some tool groups fail
    to load.

    Args:
        registry: The ToolRegistry instance to register tools with (creates new one if None)
        embedding_service: Optional embedding service instance for actual functionality
    
    Returns:
        List of tools if registry is None, otherwise None

    The function registers tools in the following categories:
    - Embedding tools: Core embedding generation, batch processing, and multimodal support
    - Search tools: Semantic search capabilities
    - Analysis tools: Clustering, quality assessment, and dimensionality reduction
    - Storage tools: Storage and collection management
    - Data processing tools: Chunking, dataset loading, and format conversion
    - Authentication tools: User authentication, token validation, and user info
    - Admin tools: Endpoint management, user administration, and system configuration
    - Cache tools: Cache statistics, management, and monitoring
    - Monitoring tools: Health checks, metrics collection, system monitoring, and alerting
    - Background task tools: Task status monitoring, management, and queue operations
    - Rate limiting tools: Configuration, monitoring, and management of rate limits
    - Index management tools: Index loading, shard management, and status monitoring
    - Sparse embedding tools: Sparse embedding generation, indexing, and search
    - IPFS cluster tools: Cluster management, Storacha integration, and pinning
    - Session management tools: Session creation, monitoring, and cleanup
    - Vector store tools: Vector store creation, search, and optimization
    - Workflow orchestration tools: Pipeline execution, workflow management, and monitoring
        registry (ToolRegistry, optional): The ToolRegistry instance to register tools with.
            If None, a new ToolRegistry instance will be created internally.
        embedding_service (optional): The embedding service instance that provides the
            actual embedding functionality. Some tools require this service to operate.
            If None, only tools that don't require embedding services will be registered.
        List or None: If registry is None (meaning a new registry was created internally),
            returns a list of all successfully registered tools. If an existing registry
            was passed, returns None as the tools are registered directly with the
            provided registry.

    Raises:
        No exceptions are raised directly. All import and registration errors are caught
        and logged as warnings or errors, allowing the function to continue registering
        other available tools.

    Note:
        - The function uses defensive programming practices, continuing to register other
          tools even if some fail to import or initialize
        - Detailed logging is provided for debugging tool registration issues
        - Some tools are conditionally registered based on the availability of the
          embedding_service parameter
        - The function maintains backwards compatibility by supporting both standalone
          usage (creating its own registry) and integration with existing registries

    Example:
        >>> # Create new registry with all available tools
        >>> tools = initialize_laion_tools()
        >>> 
        >>> # Register tools with existing registry
        >>> registry = ToolRegistry()
        >>> embedding_svc = MyEmbeddingService()
        >>> initialize_laion_tools(registry, embedding_svc)
    """
    logger.info("Initializing LAION embedding tools...")

    if registry is None:
        registry = ToolRegistry()
        return_tools = True
    else:
        return_tools = False

    _register_embedding_tools(registry, embedding_service)
    _register_search_tools(registry, embedding_service)
    _register_analysis_tools(registry, embedding_service)
    _register_storage_tools(registry, embedding_service)
    _register_data_processing_tools(registry, embedding_service)
    _register_auth_tools(registry, embedding_service)
    _register_admin_tools(registry, embedding_service)
    _register_cache_tools(registry, embedding_service)
    _register_monitoring_tools_group(registry, embedding_service)
    _register_background_task_tools(registry, embedding_service)
    _register_rate_limiting_tools(registry, embedding_service)
    _register_index_management_tools(registry, embedding_service)
    _register_sparse_embedding_tools(registry, embedding_service)
    _register_ipfs_cluster_tools(registry, embedding_service)
    _register_session_tools(registry, embedding_service)
    _register_embedding_generation_tools(registry)
    _register_shard_embedding_tools(registry)
    _register_vector_store_tools(registry)
    _register_workflow_tools(registry)

    logger.info(f"Successfully registered {len(registry.get_all_tools())} tools total")

    if return_tools:
        return registry.get_all_tools()

    return None
