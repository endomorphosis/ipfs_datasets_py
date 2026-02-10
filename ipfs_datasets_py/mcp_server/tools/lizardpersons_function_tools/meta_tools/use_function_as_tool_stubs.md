# Function and Class stubs from '<repo-root>/ipfs_datasets_py/ipfs_datasets_py/mcp_server/tools/lizardpersons_function_tools/meta_tools/use_function_as_tool.py'

Files last updated: 1751408933.7564564

Stub file last updated: 2025-07-07 01:10:14

## _call_function_and_return_results

```python
def _call_function_and_return_results(function_name: str, function: Callable, args_dict: dict[str, Any] = None, kwargs_dict: dict[str, Any] = None) -> dict[str, Any]:
    """
    Call a function with the provided arguments and return the result.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## _verify_tool_call

```python
def _verify_tool_call(function_name: str, functions_docstring: str) -> None:
    """
    Verify that the function exists in the tools directory and that its docstring matches the provided docstring.
    This is to make sure the LLM didn't hallucinate the function or its docstring.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## use_function_as_tool

```python
def use_function_as_tool(function_name: str, functions_docstring: str, args_dict: dict[str, Any] = None, kwargs_dict: dict[str, Any] = None) -> dict[str, Any]:
    """
    Use a function in this folder as a tool.

Args:
    function_name (str): The name of the function to use as a tool.
    functions_docstring (str): The docstring of the function to use as a tool.
    args_dict (dict[str, Any]): A dictionary of positional arguments to pass to the function.
        The order of the keys must match the order of the function's arguments.
    kwargs_dict (dict[str, Any]): A dictionary of keyword arguments to pass to the function.

Returns:
    dict: A dictionary with the following:
        - The name of the function.
        - The result of the function call, if any.
Raises:
    FileNotFoundError: If the function is not found in the tools directory.
    ImportError: If the module for the function cannot be imported.
    AttributeError: If the function isn't in the module or isn't callable.
    ValueError: If there is an error calling the function.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A
