# Function and Class stubs from '/home/kylerose1946/ipfs_datasets_py/ipfs_datasets_py/mcp_server/utils/_run_tool.py'

Files last updated: 1749503426.318964

Stub file last updated: 2025-07-07 02:17:31

## _RunTool

```python
class _RunTool:
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## __call__

```python
def __call__(self, *args, **kwargs) -> CallToolResultType:
    """
    Route to the appropriate tool caller based on the given arguments and keyword arguments.
    """
```
* **Async:** False
* **Method:** True
* **Class:** _RunTool

## __init__

```python
def __init__(self, configs: Configs = None, resources: dict[str, Callable] = None) -> None:
```
* **Async:** False
* **Method:** True
* **Class:** _RunTool

## _run_cli_tool

```python
def _run_cli_tool(self, cmd_list: list[str], func_name: str) -> CallToolResultType:
    """
    Run a command line tool with the given command and function name.

Args:
    cmd_list: The command to run.
    func_name: The name of the command line tool that called this.

Returns:
    A CallToolResultType object containing the result of the command.
    """
```
* **Async:** False
* **Method:** True
* **Class:** _RunTool

## _run_func_tool

```python
def _run_func_tool(self, func: Callable, *args, **kwargs) -> CallToolResultType:
    """
    Run a function tool with the given function and arguments.

This can be used to run both synchronous and asynchronous functions.

Args:
    func: The function to execute.
    *args: Positional arguments to pass to the function.
    **kwargs: Keyword arguments to pass to the function.
    
Returns:
    The result of the function execution wrapped in a CallToolResultType.
    """
```
* **Async:** False
* **Method:** True
* **Class:** _RunTool

## result

```python
def result(self, result: Any) -> CallToolResultType:
    """
    Format the result of a tool call.

Args:
    result: The result of the tool call, can be an arbitrary type or an exception.

Returns:
    A CallToolResultType object containing the result.
    """
```
* **Async:** False
* **Method:** True
* **Class:** _RunTool

## return_results

```python
def return_results(input: Any) -> CallToolResultType:
    """
    Return the result of a tool call.

Args:
    input: The result of the tool call, can be an arbitrary type or an exception.

Returns:
    A CallToolResultType object containing the result.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## run_tool

```python
def run_tool(*args, **kwargs) -> CallToolResultType:
    """
    Run a tool with the given arguments and keyword arguments.

This function can run both function tools and command line tools.

Args:
    *args: Positional arguments to pass to the tool
    **kwargs: Keyword arguments to pass to the tool

Returns:
    A CallToolResult object containing the result of the tool call.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A
