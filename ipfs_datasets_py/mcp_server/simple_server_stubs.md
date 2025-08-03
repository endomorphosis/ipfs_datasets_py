# Function and Class stubs from '/home/kylerose1946/ipfs_datasets_py/ipfs_datasets_py/mcp_server/simple_server.py'

Files last updated: 1751408933.6764565

Stub file last updated: 2025-07-07 02:35:43

## SimpleCallResult

```python
class SimpleCallResult:
    """
    Simple representation of a tool call result.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## SimpleIPFSDatasetsMCPServer

```python
class SimpleIPFSDatasetsMCPServer:
    """
    Simplified MCP Server for IPFS Datasets Python.

This class provides a simpler server implementation that uses Flask directly
and doesn't rely on the modelcontextprotocol package.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## __init__

```python
def __init__(self, result: Any, error: Optional[str] = None):
```
* **Async:** False
* **Method:** True
* **Class:** SimpleCallResult

## __init__

```python
def __init__(self, server_configs: Optional[Configs] = None):
    """
    Initialize the Simple IPFS Datasets MCP Server.

Args:
    server_configs: Optional configuration object. If not provided, the default configs will be used.
    """
```
* **Async:** False
* **Method:** True
* **Class:** SimpleIPFSDatasetsMCPServer

## _register_routes

```python
def _register_routes(self):
    """
    Register the Flask routes.
    """
```
* **Async:** False
* **Method:** True
* **Class:** SimpleIPFSDatasetsMCPServer

## _register_tools_from_subdir

```python
def _register_tools_from_subdir(self, subdir_path: Path):
    """
    Register all tools from a subdirectory.

Args:
    subdir_path: Path to the subdirectory containing tools
    """
```
* **Async:** False
* **Method:** True
* **Class:** SimpleIPFSDatasetsMCPServer

## call_tool

```python
@self.app.route("/tools/<tool_name>", methods=['POST'])
def call_tool(tool_name):
    """
    Call a specific tool with parameters.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## import_argparse_program

```python
def import_argparse_program(directory_path: Path) -> Dict[str, Any]:
    """
    Import argparse programs from a directory.

Args:
    program_name: Name of the program to import

Returns:
    Callable function representing the program
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## import_tools_from_directory

```python
def import_tools_from_directory(directory_path: Path) -> Dict[str, Any]:
    """
    Import all tools from a directory.

Args:
    directory_path: Path to the directory containing tools

Returns:
    Dictionary of tool name -> tool function
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## list_tools

```python
@self.app.route("/tools", methods=['GET'])
def list_tools():
    """
    List available tools.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## register_tools

```python
def register_tools(self):
    """
    Register all tools with the MCP server.
    """
```
* **Async:** False
* **Method:** True
* **Class:** SimpleIPFSDatasetsMCPServer

## root

```python
@self.app.route("/", methods=['GET'])
def root():
    """
    Root endpoint.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## run

```python
def run(self, host: Optional[str] = None, port: Optional[int] = None):
    """
    Run the server.

Args:
    host: Optional host to run the server on. Defaults to the configured host.
    port: Optional port to run the server on. Defaults to the configured port.
    """
```
* **Async:** False
* **Method:** True
* **Class:** SimpleIPFSDatasetsMCPServer

## start_simple_server

```python
def start_simple_server(config_path: Optional[str] = None):
    """
    Start the MCP server.

Args:
    config_path: Optional path to a configuration file.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## to_dict

```python
def to_dict(self) -> Dict[str, Any]:
    """
    Convert the result to a dictionary.
    """
```
* **Async:** False
* **Method:** True
* **Class:** SimpleCallResult
