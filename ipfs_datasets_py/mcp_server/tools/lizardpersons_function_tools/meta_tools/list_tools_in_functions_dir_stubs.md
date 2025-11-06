# Function and Class stubs from '/home/kylerose1946/ipfs_datasets_py/ipfs_datasets_py/mcp_server/tools/lizardpersons_function_tools/meta_tools/list_tools_in_functions_dir.py'

Files last updated: 1751408933.7464564

Stub file last updated: 2025-07-07 01:10:14

## list_tools_in_functions_dir

```python
def list_tools_in_functions_dir(get_docstring: bool = True) -> list[dict[str, str]]:
    """
    Lists all function-based tool files in the tools directory, excluding itself.

Args:
    get_docstring (bool): If True, gets the tool's docstring. Defaults to True.

Returns:
    list[dict[str, str]]: List of dictionaries containing Python filenames (without .py extension).
        If `get_docstring` is True, each dictionary will also contain the tool's docstring.

Raises:
    ValueError: If get_docstring is not a boolean.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A
