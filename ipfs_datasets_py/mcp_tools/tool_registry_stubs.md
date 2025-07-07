# Function and Class stubs from '/home/kylerose1946/ipfs_datasets_py/ipfs_datasets_py/mcp_tools/tool_registry.py'

Files last updated: 1751498782.2184474

Stub file last updated: 2025-07-07 01:54:19

## ClaudeMCPTool

```python
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
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## ToolRegistry

```python
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
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## __init__

```python
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
```
* **Async:** False
* **Method:** True
* **Class:** ClaudeMCPTool

## __init__

```python
def __init__(self):
    """
    Initialize the tool registry.

This initializes an empty registry for managing Claude MCP tools with the following attributes:

Attributes:
    _tools (Dict[str, ClaudeMCPTool]): Dictionary mapping tool names to their corresponding ClaudeMCPTool instances
    _categories (Dict[str, List[str]]): Dictionary mapping category names to lists of tool names in that category
    _tags (Dict[str, List[str]]): Dictionary mapping tag names to lists of tool names associated with that tag
    total_executions (int): Counter tracking the total number of tool executions across all registered tools
    """
```
* **Async:** False
* **Method:** True
* **Class:** ToolRegistry

## execute

```python
@abstractmethod
async def execute(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
    """
    Execute the tool with the provided parameters and return the result.

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
```
* **Async:** True
* **Method:** True
* **Class:** ClaudeMCPTool

## execute_tool

```python
async def execute_tool(self, tool_name: str, parameters: Dict[str, Any]) -> Dict[str, Any]:
    """
    Execute a tool with the given parameters and track execution statistics.

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
```
* **Async:** True
* **Method:** True
* **Class:** ToolRegistry

## get_all_tools

```python
def get_all_tools(self) -> List[ClaudeMCPTool]:
    """
    Get all registered tools.
    """
```
* **Async:** False
* **Method:** True
* **Class:** ToolRegistry

## get_categories

```python
def get_categories(self) -> List[str]:
    """
    Get all available categories.
    """
```
* **Async:** False
* **Method:** True
* **Class:** ToolRegistry

## get_schema

```python
def get_schema(self) -> Dict[str, Any]:
    """
    Get the complete tool schema with all metadata.

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
```
* **Async:** False
* **Method:** True
* **Class:** ClaudeMCPTool

## get_tags

```python
def get_tags(self) -> List[str]:
    """
    Get all available tags.
    """
```
* **Async:** False
* **Method:** True
* **Class:** ToolRegistry

## get_tool

```python
def get_tool(self, tool_name: str) -> Optional[ClaudeMCPTool]:
    """
    Retrieve a tool instance by its unique name identifier.

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
```
* **Async:** False
* **Method:** True
* **Class:** ToolRegistry

## get_tool_statistics

```python
def get_tool_statistics(self) -> Dict[str, Any]:
    """
    Get comprehensive usage statistics for all tools and registry.

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
```
* **Async:** False
* **Method:** True
* **Class:** ToolRegistry

## get_tools_by_category

```python
def get_tools_by_category(self, category: str) -> List[ClaudeMCPTool]:
    """
    Get tools by category.
    """
```
* **Async:** False
* **Method:** True
* **Class:** ToolRegistry

## get_tools_by_tag

```python
def get_tools_by_tag(self, tag: str) -> List[ClaudeMCPTool]:
    """
    Get tools by tag.
    """
```
* **Async:** False
* **Method:** True
* **Class:** ToolRegistry

## has_tool

```python
def has_tool(self, tool_name: str) -> bool:
    """
    Check if a tool is registered.
    """
```
* **Async:** False
* **Method:** True
* **Class:** ToolRegistry

## initialize_laion_tools

```python
def initialize_laion_tools(registry: ToolRegistry = None, embedding_service = None):
    """
    Initialize and register all LAION embedding tools with the tool registry.

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
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## list_tools

```python
def list_tools(self) -> List[Dict[str, Any]]:
    """
    List all tools with their schemas.
    """
```
* **Async:** False
* **Method:** True
* **Class:** ToolRegistry

## register_tool

```python
def register_tool(self, tool: ClaudeMCPTool) -> None:
    """
    Register a tool with the registry.

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
```
* **Async:** False
* **Method:** True
* **Class:** ToolRegistry

## run

```python
async def run(self, **kwargs) -> Dict[str, Any]:
    """
    Execute the tool with provided keyword arguments and update usage statistics.

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
```
* **Async:** True
* **Method:** True
* **Class:** ClaudeMCPTool

## search_tools

```python
def search_tools(self, query: str) -> List[ClaudeMCPTool]:
    """
    Search for tools by name, description, or tags using a flexible query string.

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
```
* **Async:** False
* **Method:** True
* **Class:** ToolRegistry

## unregister_tool

```python
def unregister_tool(self, tool_name: str) -> bool:
    """
    Unregister a tool from the registry and clean up all associated references.

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
```
* **Async:** False
* **Method:** True
* **Class:** ToolRegistry

## validate_tool_parameters

```python
def validate_tool_parameters(self, tool_name: str, parameters: Dict[str, Any]) -> bool:
    """
    Validate parameters against a tool's input schema with comprehensive validation.

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
```
* **Async:** False
* **Method:** True
* **Class:** ToolRegistry
