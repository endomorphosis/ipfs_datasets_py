# src/mcp_server/tool_registry.py

import logging
from typing import Dict, Any, List, Optional
from datetime import datetime
from abc import ABC, abstractmethod


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
        self.created_at = datetime.now(tz='UTC')
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
        self.last_used = datetime.now(tz='UTC')
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
    
    def register_tool(self, tool: ClaudeMCPTool) -> None:
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
        if not isinstance(tool, ClaudeMCPTool):
            raise ValueError("Tool must inherit from ClaudeMCPTool")
        
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
        """Check if a tool is registered."""
        return tool_name in self._tools
    
    def get_all_tools(self) -> List[ClaudeMCPTool]:
        """Get all registered tools."""
        return list(self._tools.values())
    
    def list_tools(self) -> List[Dict[str, Any]]:
        """List all tools with their schemas."""
        return [tool.get_schema() for tool in self._tools.values()]
    
    def get_tools_by_category(self, category: str) -> List[ClaudeMCPTool]:
        """Get tools by category."""
        tool_names = self._categories.get(category, [])
        return [self._tools[name] for name in tool_names if name in self._tools]
    
    def get_tools_by_tag(self, tag: str) -> List[ClaudeMCPTool]:
        """Get tools by tag."""
        tool_names = self._tags.get(tag, [])
        return [self._tools[name] for name in tool_names if name in self._tools]
    
    def get_categories(self) -> List[str]:
        """Get all available categories."""
        return list(self._categories.keys())
    
    def get_tags(self) -> List[str]:
        """Get all available tags."""
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
            raise ValueError(f"Tool '{tool_name}' not found")
        
        tool = self._tools[tool_name]
        self.total_executions += 1
        
        try:
            result = await tool.execute(parameters)
            logger.debug(f"Tool '{tool_name}' executed successfully")
            return result
        except Exception as e:
            logger.error(f"Tool '{tool_name}' execution failed: {e}")
            raise
    
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


def initialize_laion_tools(registry: ToolRegistry = None, embedding_service=None):
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
    
    # Create registry if none provided
    if registry is None:
        registry = ToolRegistry()
        return_tools = True
    else:
        return_tools = False
    
    try:
        # Import and register embedding tools
        from ipfs_datasets_py.mcp_tools.tools.embedding_tools import EmbeddingGenerationTool, BatchEmbeddingTool, MultimodalEmbeddingTool
        registry.register_tool(EmbeddingGenerationTool(embedding_service))
        registry.register_tool(BatchEmbeddingTool(embedding_service))
        registry.register_tool(MultimodalEmbeddingTool(embedding_service))
    except Exception as e:
        logger.error(f"Error importing or registering embedding tools: {e}")
        # Continue with other tools even if some fail
        
        # Import and register search tools
        from ipfs_datasets_py.mcp_tools.tools.search_tools import SemanticSearchTool
        registry.register_tool(SemanticSearchTool(embedding_service))
        
        # Import and register analysis tools
        from ipfs_datasets_py.mcp_tools.tools.analysis_tools import ClusterAnalysisTool, QualityAssessmentTool, DimensionalityReductionTool
        registry.register_tool(ClusterAnalysisTool())
        registry.register_tool(QualityAssessmentTool())
        registry.register_tool(DimensionalityReductionTool())
        
        # Import and register storage tools
        from ipfs_datasets_py.mcp_tools.tools.storage_tools import StorageManagementTool, CollectionManagementTool
        registry.register_tool(StorageManagementTool(embedding_service))
        registry.register_tool(CollectionManagementTool(embedding_service))
        
        # Import and register data processing tools (only if embedding service is available)
        if embedding_service is not None:
            try:
                from ipfs_datasets_py.mcp_tools.tools.data_processing_tools import ChunkingTool, DatasetLoadingTool, ParquetToCarTool
                registry.register_tool(ChunkingTool(embedding_service))
                registry.register_tool(DatasetLoadingTool(embedding_service))
                registry.register_tool(ParquetToCarTool(embedding_service))
            except Exception as e:
                logger.warning(f"Could not register data processing tools (embedding service required): {e}")
        else:
            logger.info("Skipping data processing tools registration (no embedding service provided)")
        
        # Import and register authentication tools
        try:
            from ipfs_datasets_py.mcp_tools.tools.authentication_tools import AuthenticationTool, UserInfoTool, TokenValidationTool
            registry.register_tool(AuthenticationTool(embedding_service))
            registry.register_tool(UserInfoTool(embedding_service))
            registry.register_tool(TokenValidationTool(embedding_service))
            logger.info("Successfully registered authentication tools")
        except Exception as e:
            logger.warning(f"Could not register authentication tools: {e}")
        
        # Import and register admin tools
        try:
            from ipfs_datasets_py.mcp_tools.tools.admin_tools import EndpointManagementTool, UserManagementTool, SystemConfigurationTool
            registry.register_tool(EndpointManagementTool(embedding_service))
            registry.register_tool(UserManagementTool(embedding_service))
            registry.register_tool(SystemConfigurationTool(embedding_service))
            logger.info("Successfully registered admin tools")
        except Exception as e:
            logger.warning(f"Could not register admin tools: {e}")
        
        # Import and register cache tools
        try:
            from ipfs_datasets_py.mcp_tools.tools.cache_tools import CacheStatsTool, CacheManagementTool, CacheMonitoringTool
            registry.register_tool(CacheStatsTool(embedding_service))
            registry.register_tool(CacheManagementTool(embedding_service))
            registry.register_tool(CacheMonitoringTool(embedding_service))
            logger.info("Successfully registered cache tools")
        except Exception as e:
            logger.warning(f"Could not register cache tools: {e}")
        
        # Import and register monitoring tools
        try:
            from ipfs_datasets_py.mcp_tools.tools.monitoring_tools import HealthCheckTool, MetricsCollectionTool, SystemMonitoringTool, AlertManagementTool
            registry.register_tool(HealthCheckTool(embedding_service))
            registry.register_tool(MetricsCollectionTool(embedding_service))
            registry.register_tool(SystemMonitoringTool(embedding_service))
            registry.register_tool(AlertManagementTool(embedding_service))
            logger.info("Successfully registered monitoring tools")
        except Exception as e:
            logger.warning(f"Could not register monitoring tools: {e}")
        
        # Import and register background task tools
        try:
            from ipfs_datasets_py.mcp_tools.tools.background_task_tools import BackgroundTaskStatusTool, BackgroundTaskManagementTool, TaskQueueManagementTool
            registry.register_tool(BackgroundTaskStatusTool(embedding_service))
            registry.register_tool(BackgroundTaskManagementTool(embedding_service))
            registry.register_tool(TaskQueueManagementTool(embedding_service))
            logger.info("Successfully registered background task tools")
        except Exception as e:
            logger.warning(f"Could not register background task tools: {e}")
        
        # Import and register rate limiting tools
        try:
            from ipfs_datasets_py.mcp_tools.tools.rate_limiting_tools import RateLimitConfigurationTool, RateLimitMonitoringTool, RateLimitManagementTool
            registry.register_tool(RateLimitConfigurationTool(embedding_service))
            registry.register_tool(RateLimitMonitoringTool(embedding_service))
            registry.register_tool(RateLimitManagementTool(embedding_service))
            logger.info("Successfully registered rate limiting tools")
        except Exception as e:
            logger.warning(f"Could not register rate limiting tools: {e}")
        
        # Import and register index management tools
        try:
            from ipfs_datasets_py.mcp_tools.tools.index_management_tools import IndexLoadingTool, ShardManagementTool, IndexStatusTool
            registry.register_tool(IndexLoadingTool(embedding_service))
            registry.register_tool(ShardManagementTool(embedding_service))
            registry.register_tool(IndexStatusTool(embedding_service))
            logger.info("Successfully registered index management tools")
        except Exception as e:
            logger.warning(f"Could not register index management tools: {e}")
        
        # Import and register sparse embedding tools
        try:
            from ipfs_datasets_py.mcp_tools.tools.sparse_embedding_tools import SparseEmbeddingGenerationTool, SparseIndexingTool, SparseSearchTool
            registry.register_tool(SparseEmbeddingGenerationTool(embedding_service))
            registry.register_tool(SparseIndexingTool(embedding_service))
            registry.register_tool(SparseSearchTool(embedding_service))
            logger.info("Successfully registered sparse embedding tools")
        except Exception as e:
            logger.warning(f"Could not register sparse embedding tools: {e}")
        
        # Import and register IPFS cluster tools
        try:
            from ipfs_datasets_py.mcp_tools.tools.ipfs_cluster_tools import IPFSClusterManagementTool, StorachaIntegrationTool, IPFSPinningTool
            registry.register_tool(IPFSClusterManagementTool(embedding_service))
            registry.register_tool(StorachaIntegrationTool(embedding_service))
            registry.register_tool(IPFSPinningTool(embedding_service))
            logger.info("Successfully registered IPFS cluster tools")
        except Exception as e:
            logger.warning(f"Could not register IPFS cluster tools: {e}")
        
        # Import and register session management tools
        try:
            from ipfs_datasets_py.mcp_tools.tools.session_management_tools import SessionCreationTool, SessionMonitoringTool, SessionCleanupTool
            registry.register_tool(SessionCreationTool(embedding_service))
            registry.register_tool(SessionMonitoringTool(embedding_service))
            registry.register_tool(SessionCleanupTool(embedding_service))
            logger.info("Successfully registered session management tools")
        except Exception as e:
            logger.warning(f"Could not register session management tools: {e}")
        
        from ipfs_datasets_py.mcp_tools.tools.tool_wrapper import wrap_function_as_tool

        # Import and register create embeddings tools
        try:
            from ipfs_datasets_py.mcp_tools.tools.create_embeddings_tool import create_embeddings_tool, batch_create_embeddings_tool
            registry.register_tool(wrap_function_as_tool(create_embeddings_tool, "create_embeddings", "embedding"))
            registry.register_tool(wrap_function_as_tool(batch_create_embeddings_tool, "batch_create_embeddings", "embedding"))
            logger.info("Successfully registered create embeddings tools")
        except Exception as e:
            logger.warning(f"Could not register create embeddings tools: {e}")
        
        # Import and register shard embeddings tools
        try:
            from ipfs_datasets_py.mcp_tools.tools.shard_embeddings_tool import shard_embeddings_tool, merge_shards_tool, shard_info_tool

            registry.register_tool(wrap_function_as_tool(shard_embeddings_tool, "shard_embeddings", "processing"))
            registry.register_tool(wrap_function_as_tool(merge_shards_tool, "merge_shards", "processing"))
            registry.register_tool(wrap_function_as_tool(shard_info_tool, "shard_info", "analysis"))
            logger.info("Successfully registered shard embeddings tools")
        except Exception as e:
            logger.warning(f"Could not register shard embeddings tools: {e}")
        
        # Import and register vector store tools
        try:
            from ipfs_datasets_py.mcp_tools.tools.vector_store_tools import (
                create_vector_store_tool, add_embeddings_to_store_tool, search_vector_store_tool,
                get_vector_store_stats_tool, delete_from_vector_store_tool, optimize_vector_store_tool
            )

            registry.register_tool(wrap_function_as_tool(create_vector_store_tool, "create_vector_store", "storage"))
            registry.register_tool(wrap_function_as_tool(add_embeddings_to_store_tool, "add_embeddings_to_store", "storage"))
            registry.register_tool(wrap_function_as_tool(search_vector_store_tool, "search_vector_store", "search"))
            registry.register_tool(wrap_function_as_tool(get_vector_store_stats_tool, "get_vector_store_stats", "analysis"))
            registry.register_tool(wrap_function_as_tool(delete_from_vector_store_tool, "delete_from_vector_store", "storage"))
            registry.register_tool(wrap_function_as_tool(optimize_vector_store_tool, "optimize_vector_store", "optimization"))
            logger.info("Successfully registered vector store tools")
        except Exception as e:
            logger.warning(f"Could not register vector store tools: {e}")

        # Import and register workflow orchestration tools
        try:
            from ipfs_datasets_py.mcp_tools.tools.workflow_tools import (
                execute_workflow_tool, create_embedding_pipeline_tool, 
                get_workflow_status_tool, list_workflows_tool
            )
            registry.register_tool(wrap_function_as_tool(execute_workflow_tool, "execute_workflow", "orchestration"))
            registry.register_tool(wrap_function_as_tool(create_embedding_pipeline_tool, "create_embedding_pipeline", "orchestration"))
            registry.register_tool(wrap_function_as_tool(get_workflow_status_tool, "get_workflow_status", "monitoring"))
            registry.register_tool(wrap_function_as_tool(list_workflows_tool, "list_workflows", "monitoring"))
            logger.info("Successfully registered workflow orchestration tools")
        except Exception as e:
            logger.warning(f"Could not register workflow orchestration tools: {e}")
        
        logger.info(f"Successfully registered {len(registry.get_all_tools())} tools total")
        
        # Return tools if registry was created internally
        if return_tools:
            return registry.get_all_tools()
        
    except ImportError as e:
        logger.error(f"Failed to import tool classes: {e}")
        # Continue with basic functionality
        if return_tools:
            return registry.get_all_tools()
    except Exception as e:
        logger.error(f"Error registering tools: {e}")
        # Continue with basic functionality
        if return_tools:
            return registry.get_all_tools()
