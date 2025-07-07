# Function and Class stubs from '/home/kylerose1946/ipfs_datasets_py/ipfs_datasets_py/mcp_server/tools/development_tools/base_tool.py'

Files last updated: 1751408933.6964564

Stub file last updated: 2025-07-07 01:10:13

## BaseDevelopmentTool

```python
class BaseDevelopmentTool(ABC):
    """
    Base class for all development tools.

Provides:
- Consistent error handling
- Audit logging integration
- Input validation
- Standardized result format
- IPFS integration hooks
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## DevelopmentToolError

```python
class DevelopmentToolError(Exception):
    """
    Base exception for development tool errors.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## DevelopmentToolExecutionError

```python
class DevelopmentToolExecutionError(DevelopmentToolError):
    """
    Raised when tool execution fails.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## DevelopmentToolValidationError

```python
class DevelopmentToolValidationError(DevelopmentToolError):
    """
    Raised when tool input validation fails.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## __init__

```python
def __init__(self, name: str, description: str, category: str = "development"):
```
* **Async:** False
* **Method:** True
* **Class:** BaseDevelopmentTool

## _audit_log

```python
async def _audit_log(self, action: str, details: Optional[Dict[str, Any]] = None) -> None:
    """
    Log audit event if audit logging is available.

Args:
    action: Action being performed
    details: Additional details to log
    """
```
* **Async:** True
* **Method:** True
* **Class:** BaseDevelopmentTool

## _create_error_result

```python
def _create_error_result(self, error: str, message: str, details: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Create standardized error result.

Args:
    error: Error type/code
    message: Human-readable error message
    details: Optional error details

Returns:
    Standardized error result dictionary
    """
```
* **Async:** False
* **Method:** True
* **Class:** BaseDevelopmentTool

## _create_success_result

```python
def _create_success_result(self, result: Any, metadata: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Create standardized success result.

Args:
    result: The actual result data
    metadata: Optional metadata to include

Returns:
    Standardized result dictionary
    """
```
* **Async:** False
* **Method:** True
* **Class:** BaseDevelopmentTool

## _execute_core

```python
@abstractmethod
async def _execute_core(self, **kwargs) -> Dict[str, Any]:
    """
    Core execution logic to be implemented by each tool.

Args:
    **kwargs: Tool-specific parameters

Returns:
    Tool execution result
    """
```
* **Async:** True
* **Method:** True
* **Class:** BaseDevelopmentTool

## _get_timestamp

```python
def _get_timestamp(self) -> str:
    """
    Get current timestamp in ISO format.
    """
```
* **Async:** False
* **Method:** True
* **Class:** BaseDevelopmentTool

## _validate_output_dir

```python
def _validate_output_dir(self, output_dir: Union[str, Path]) -> Path:
    """
    Validate and create output directory if needed.

Args:
    output_dir: Output directory path

Returns:
    Validated Path object
    """
```
* **Async:** False
* **Method:** True
* **Class:** BaseDevelopmentTool

## _validate_path

```python
def _validate_path(self, path: Union[str, Path], must_exist: bool = True) -> Path:
    """
    Validate and convert path input.

Args:
    path: Path to validate
    must_exist: Whether the path must exist

Returns:
    Validated Path object

Raises:
    DevelopmentToolValidationError: If path validation fails
    """
```
* **Async:** False
* **Method:** True
* **Class:** BaseDevelopmentTool

## base_tool

```python
async def base_tool():
    """
    Base class for all development tools.

Provides:
- Consistent error handling
- Audit logging integration
- Input validation
- Standardized result format
- IPFS integration hooks
    """
```
* **Async:** True
* **Method:** False
* **Class:** N/A

## development_tool_mcp_wrapper

```python
def development_tool_mcp_wrapper(tool_class: str) -> Dict[str, Any]:
    """
    Decorator to wrap a development tool class for MCP registration.

Args:
    tool_class: Name of the BaseDevelopmentTool subclass or function

Returns:
    Dict with success/error result
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## execute

```python
async def execute(self, **kwargs) -> Dict[str, Any]:
    """
    Execute the tool with comprehensive error handling and logging.

Args:
    **kwargs: Tool-specific parameters

Returns:
    Standardized result dictionary
    """
```
* **Async:** True
* **Method:** True
* **Class:** BaseDevelopmentTool
