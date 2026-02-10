# Function and Class stubs from '<repo-root>/ipfs_datasets_py/ipfs_datasets_py/mcp_server/tools/lizardpersons_function_tools/prototyping_tools/json_to_python_file.py'

Files last updated: 1749503535.8821542

Stub file last updated: 2025-07-07 01:10:14

## _JsonToAst

```python
class _JsonToAst:
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## _NODE_MAP

```python
@property
def _NODE_MAP(self) -> dict[str, dict[str, Any]]:
```
* **Async:** False
* **Method:** True
* **Class:** _JsonToAst

## _UnKnownNodeException

```python
class _UnKnownNodeException(Exception):
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
* **Class:** _JsonToAst

## _resolve_argument

```python
def _resolve_argument(self, arg: Any):
```
* **Async:** False
* **Method:** True
* **Class:** _JsonToAst

## _resolve_node

```python
def _resolve_node(self, node: dict) -> Any:
```
* **Async:** False
* **Method:** True
* **Class:** _JsonToAst

## json_to_python_file

```python
def json_to_python_file(data: dict | str, output_path: str) -> None:
    """
    Convert a JSON file or JSON-like dictionary representation of a Python file into an actual Python file.

Args:
    data (dict | str): The JSON data representing the Python file. If a string is provided, it is parsed as path to JSON file.
    output_path (str): The path where the Python file will be saved.

Returns:
    None: A python file of the converted code.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A
