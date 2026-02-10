# Function and Class stubs from '<repo-root>/ipfs_datasets_py/ipfs_datasets_py/mcp_server/tools/tool_wrapper.py'

Files last updated: 1751514471.5808518

Stub file last updated: 2025-07-07 01:10:14

## EnhancedBaseMCPTool

```python
class EnhancedBaseMCPTool(ABC):
    """
    Enhanced base class for MCP Tools with production features.
Includes monitoring, caching, validation, and error handling.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## FunctionToolWrapper

```python
class FunctionToolWrapper(BaseMCPTool):
    """
    Wrapper to convert a standalone function into an MCP tool.

This class takes any function (sync or async) and wraps it to be
compatible with our MCP tool system.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## __init__

```python
def __init__(self):
```
* **Async:** False
* **Method:** True
* **Class:** EnhancedBaseMCPTool

## __init__

```python
def __init__(self, function: Callable, tool_name: str, category: str = "general", description: Optional[str] = None, tags: Optional[list] = None):
```
* **Async:** False
* **Method:** True
* **Class:** FunctionToolWrapper

## _extract_input_schema

```python
def _extract_input_schema(self) -> Dict[str, Any]:
    """
    Extract input schema from function signature and type hints.
    """
```
* **Async:** False
* **Method:** True
* **Class:** FunctionToolWrapper

## _generate_cache_key

```python
def _generate_cache_key(self, parameters: Dict[str, Any]) -> str:
    """
    Generate cache key from parameters.
    """
```
* **Async:** False
* **Method:** True
* **Class:** EnhancedBaseMCPTool

## _is_cache_valid

```python
def _is_cache_valid(self, cache_entry: Dict[str, Any]) -> bool:
    """
    Check if cache entry is still valid.
    """
```
* **Async:** False
* **Method:** True
* **Class:** EnhancedBaseMCPTool

## _python_type_to_json_type

```python
def _python_type_to_json_type(self, python_type) -> str:
    """
    Convert Python type annotations to JSON schema types.
    """
```
* **Async:** False
* **Method:** True
* **Class:** FunctionToolWrapper

## call

```python
async def call(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
    """
    Enhanced call method with monitoring, caching, and validation.
    """
```
* **Async:** True
* **Method:** True
* **Class:** EnhancedBaseMCPTool

## clear_cache

```python
def clear_cache(self):
    """
    Clear the tool's cache.
    """
```
* **Async:** False
* **Method:** True
* **Class:** EnhancedBaseMCPTool

## disable_caching

```python
def disable_caching(self):
    """
    Disable caching for this tool.
    """
```
* **Async:** False
* **Method:** True
* **Class:** EnhancedBaseMCPTool

## enable_caching

```python
def enable_caching(self, ttl_seconds: int = 300):
    """
    Enable caching for this tool.
    """
```
* **Async:** False
* **Method:** True
* **Class:** EnhancedBaseMCPTool

## execute

```python
@abstractmethod
async def execute(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
    """
    Execute the tool with given parameters.
    """
```
* **Async:** True
* **Method:** True
* **Class:** EnhancedBaseMCPTool

## execute

```python
async def execute(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
    """
    Execute the wrapped function with the given parameters.
    """
```
* **Async:** True
* **Method:** True
* **Class:** FunctionToolWrapper

## get_performance_stats

```python
def get_performance_stats(self) -> Dict[str, Any]:
    """
    Get performance statistics for this tool.
    """
```
* **Async:** False
* **Method:** True
* **Class:** EnhancedBaseMCPTool

## get_schema

```python
def get_schema(self) -> Dict[str, Any]:
    """
    Get the complete tool schema.
    """
```
* **Async:** False
* **Method:** True
* **Class:** EnhancedBaseMCPTool

## validate_parameters

```python
async def validate_parameters(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
    """
    Validate input parameters using enhanced validator.
    """
```
* **Async:** True
* **Method:** True
* **Class:** EnhancedBaseMCPTool

## wrap_function_as_tool

```python
def wrap_function_as_tool(function: Callable, tool_name: str, category: str = "general", description: Optional[str] = None, tags: Optional[list] = None) -> FunctionToolWrapper:
    """
    Convenience function to wrap a standalone function as an MCP tool.

Args:
    function: The function to wrap (sync or async)
    tool_name: Name for the tool
    category: Category for the tool (e.g., "embedding", "storage", "search")
    description: Optional description (uses function docstring if not provided)
    tags: Optional tags for the tool

Returns:
    FunctionToolWrapper instance ready for registration

Example:
    ```python
    from ipfs_datasets_py.mcp_server.tools.auth_tools.auth_tools import authenticate_user
    
    auth_tool = wrap_function_as_tool(
        authenticate_user, 
        "authenticate_user",
        category="auth",
        description="Authenticate a user with credentials",
        tags=["authentication", "security"]
    )
    ```
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## wrap_function_with_metadata

```python
def wrap_function_with_metadata(function: Callable, metadata: Dict[str, Any]) -> FunctionToolWrapper:
    """
    Wrap a function using metadata dictionary.

Args:
    function: The function to wrap
    metadata: Metadata dictionary with tool information

Returns:
    FunctionToolWrapper instance

Example:
    ```python
    metadata = {
        "name": "process_embeddings",
        "category": "embedding",
        "description": "Process embeddings for storage",
        "tags": ["embedding", "processing"]
    }
    
    tool = wrap_function_with_metadata(process_embeddings_func, metadata)
    ```
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## wrap_tools_from_module

```python
def wrap_tools_from_module(module, tool_mappings: Dict[str, Dict[str, Any]]) -> Dict[str, FunctionToolWrapper]:
    """
    Wrap multiple functions from a module using tool mappings.

Args:
    module: The module containing functions to wrap
    tool_mappings: Dictionary mapping function names to tool metadata

Returns:
    Dictionary of wrapped tools

Example:
    ```python
    from ipfs_datasets_py.mcp_server.tools.auth_tools import auth_tools
    
    mappings = {
        "authenticate_user": {
            "name": "authenticate_user",
            "category": "auth",
            "description": "Authenticate a user",
            "tags": ["auth", "security"]
        },
        "validate_token": {
            "name": "validate_token", 
            "category": "auth",
            "description": "Validate JWT token",
            "tags": ["auth", "validation"]
        }
    }
    
    tools = wrap_tools_from_module(auth_tools, mappings)
    ```
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A
