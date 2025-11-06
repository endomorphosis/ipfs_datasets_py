# Function and Class stubs from '/home/kylerose1946/ipfs_datasets_py/ipfs_datasets_py/mcp_server/tools/lizardpersons_function_tools/prototyping_tools/python_file_to_json.py'

Files last updated: 1749503777.8312867

Stub file last updated: 2025-07-07 01:10:14

## _AstToJson

```python
class _AstToJson:
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## __init__

```python
def __init__(self, builtins = None):
```
* **Async:** False
* **Method:** True
* **Class:** _AstToJson

## _ast2json

```python
def _ast2json(self, node) -> dict:
    """
    Convert an AST node to a JSON-like dictionary representation.

Args:
    node (AST): The AST node to convert.

Returns:
    dict: JSON-like representation of the AST node's public attributes.

Raises:
    AttributeError: If the node is not an instance of AST.
    """
```
* **Async:** False
* **Method:** True
* **Class:** _AstToJson

## _decode_bytes

```python
def _decode_bytes(self, value: bytes | bytearray) -> str:
    """
    Decode bytes to a string using various encodings and codecs.
    """
```
* **Async:** False
* **Method:** True
* **Class:** _AstToJson

## _decode_str

```python
def _decode_str(self, value: str) -> str:
```
* **Async:** False
* **Method:** True
* **Class:** _AstToJson

## _fix_complex_kinds

```python
def _fix_complex_kinds(self, obj: Any) -> Any:
    """
    Recursively walk through the JSON structure and fix 'kind' values 
that should represent complex numbers.
    """
```
* **Async:** False
* **Method:** True
* **Class:** _AstToJson

## _get_value

```python
def _get_value(self, attr_value: Any) -> Optional[Any]:
    """
    Match the type of the attribute value and return a JSON-compatible representation.

Args:
    attr_value (Any): The value of the attribute to convert.
    key (str): The name of the attribute, used for special cases like 'kind'.

Returns:
    Optional[str]: A JSON-compatible representation of the attribute value.
    Returns None if the value is None.
    """
```
* **Async:** False
* **Method:** True
* **Class:** _AstToJson

## _is_complex_literal

```python
def _is_complex_literal(self, value: str) -> bool:
    """
    Check if a string represents a valid Python complex number literal.

Args:
    value (str): String to check
    
Returns:
    bool: True if it's a valid complex number literal
    """
```
* **Async:** False
* **Method:** True
* **Class:** _AstToJson

## _type_name

```python
def _type_name(obj: Any) -> str:
    """
    Get the __name__ attribute of an object.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## python_file_to_json

```python
def python_file_to_json(python_file: str, is_path: bool, save_path: Optional[str] = None) -> str:
    """
    Convert a python file or python source code into a JSON-like dictionary representation.
If save_path is provided, the JSON representation will also be saved to that path.

Args:
    python_file(str): Path to the Python file or source code to parse.
    is_path(bool): If True, treat python_file as a file path; if False, treat it as file content.
    save_path(Optional[str]): Optional path to save the JSON representation to a json file.

Returns:
    str: JSON-like string representation of the AST. 
        If the JSON representation is over 20,000 characters, a truncated string of the first 19,000 characters is returned.

Raises:
    TypeError: If the python_file is not a string or save_path is not a string.
    ValueError: If the python_file does not end with '.py', save_path does not end with '.json', or if there's a failure converting the file string.
    FileNotFoundError: If the input python file does not exist.
    IOError: If there is an error reading the input python file, or saving the JSON to the specified path.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## str2json

```python
def str2json(self, string: str) -> dict[str, Any]:
    """
    Get the JSON representation of a Python source code string.
    """
```
* **Async:** False
* **Method:** True
* **Class:** _AstToJson
