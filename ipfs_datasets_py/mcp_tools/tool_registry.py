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
    Registry for managing MCP tools with categorization and execution.
    """
    def __init__(self):
        self._tools: Dict[str, ClaudeMCPTool] = {}
        self._categories: Dict[str, List[str]] = {}
        self._tags: Dict[str, List[str]] = {}
        self.total_executions = 0
        logger.info("Tool registry initialized")
    
    def register_tool(self, tool: ClaudeMCPTool) -> None:
        """Register a tool with the registry."""
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
        """Unregister a tool from the registry."""
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
        """Get a tool by name."""
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
        """Execute a tool with the given parameters."""
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
        """Get usage statistics for all tools."""
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
        """Search tools by name, description, or tags."""
        query_lower = query.lower()
        matching_tools = []
        
        for tool in self._tools.values():
            if (query_lower in tool.name.lower() or 
                query_lower in tool.description.lower() or
                any(query_lower in tag.lower() for tag in tool.tags)):
                matching_tools.append(tool)
        
        return matching_tools
    
    def validate_tool_parameters(self, tool_name: str, parameters: Dict[str, Any]) -> bool:
        """Validate parameters against tool schema."""
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
    
    Args:
        registry: The ToolRegistry instance to register tools with (creates new one if None)
        embedding_service: Optional embedding service instance for actual functionality
    
    Returns:
        List of tools if registry is None, otherwise None
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
