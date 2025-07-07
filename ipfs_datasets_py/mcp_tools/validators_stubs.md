# Function and Class stubs from '/home/kylerose1946/ipfs_datasets_py/ipfs_datasets_py/mcp_tools/validators.py'

Files last updated: 1751499406.9163177

Stub file last updated: 2025-07-07 01:54:19

## ParameterValidator

```python
class ParameterValidator:
    """
    Comprehensive parameter validation for MCP tools.
Provides validation for various data types and formats.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## ValidationError

```python
class ValidationError(ValueError):
    """
    Placeholder for ValidationError if original is not imported.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## __init__

```python
def __init__(self, param_name, message):
```
* **Async:** False
* **Method:** True
* **Class:** ValidationError

## __init__

```python
def __init__(self):
```
* **Async:** False
* **Method:** True
* **Class:** ParameterValidator

## __new__

```python
def __new__(cls):
    """
    Enforce singleton pattern for ParameterValidator.
    """
```
* **Async:** False
* **Method:** True
* **Class:** ParameterValidator

## create_tool_validator

```python
def create_tool_validator(self, schema: Dict[str, Any]):
    """
    Create a validator function for a specific tool schema.
    """
```
* **Async:** False
* **Method:** True
* **Class:** ParameterValidator

## validate_algorithm_choice

```python
def validate_algorithm_choice(self, algorithm: str, allowed_algorithms: List[str]) -> str:
    """
    Validate algorithm choice from allowed options.
    """
```
* **Async:** False
* **Method:** True
* **Class:** ParameterValidator

## validate_and_hash_args

```python
def validate_and_hash_args(self, args: Dict[str, Any]) -> str:
    """
    Validate arguments and return a hash for caching.
    """
```
* **Async:** False
* **Method:** True
* **Class:** ParameterValidator

## validate_batch_size

```python
def validate_batch_size(self, batch_size: int, max_batch_size: int = 100) -> int:
    """
    Validate batch size parameter.
    """
```
* **Async:** False
* **Method:** True
* **Class:** ParameterValidator

## validate_collection_name

```python
def validate_collection_name(self, collection_name: str) -> str:
    """
    Validate collection name format.
    """
```
* **Async:** False
* **Method:** True
* **Class:** ParameterValidator

## validate_embedding_vector

```python
def validate_embedding_vector(self, embedding: List[float]) -> List[float]:
    """
    Validate embedding vector format.
    """
```
* **Async:** False
* **Method:** True
* **Class:** ParameterValidator

## validate_file_path

```python
def validate_file_path(self, file_path: str, check_exists: bool = False, allowed_extensions: Optional[Set[str]] = None) -> str:
    """
    Validate file path format and optionally check existence.
    """
```
* **Async:** False
* **Method:** True
* **Class:** ParameterValidator

## validate_json_schema

```python
def validate_json_schema(self, data: Any, schema: Dict[str, Any], parameter_name: str = "data") -> Any:
    """
    Validate data against JSON schema.
    """
```
* **Async:** False
* **Method:** True
* **Class:** ParameterValidator

## validate_metadata

```python
def validate_metadata(self, metadata: Dict[str, Any]) -> Dict[str, Any]:
    """
    Validate metadata dictionary.
    """
```
* **Async:** False
* **Method:** True
* **Class:** ParameterValidator

## validate_model_name

```python
def validate_model_name(self, model_name: str) -> str:
    """
    Validate embedding model name.
    """
```
* **Async:** False
* **Method:** True
* **Class:** ParameterValidator

## validate_numeric_range

```python
def validate_numeric_range(self, value: Union[int, float], param_name: str, min_val: Optional[float] = None, max_val: Optional[float] = None) -> Union[int, float]:
    """
    Validate numeric value within specified range.
    """
```
* **Async:** False
* **Method:** True
* **Class:** ParameterValidator

## validate_search_filters

```python
def validate_search_filters(self, filters: Dict[str, Any]) -> Dict[str, Any]:
    """
    Validate search filter parameters.
    """
```
* **Async:** False
* **Method:** True
* **Class:** ParameterValidator

## validate_text_input

```python
def validate_text_input(self, text: str, max_length: int = 10000, min_length: int = 1, allow_empty: bool = False) -> str:
    """
    Validate text input with length constraints.
    """
```
* **Async:** False
* **Method:** True
* **Class:** ParameterValidator

## validate_url

```python
def validate_url(self, url: str) -> str:
    """
    Validate URL format.
    """
```
* **Async:** False
* **Method:** True
* **Class:** ParameterValidator

## validator

```python
def validator(args: Dict[str, Any]) -> Dict[str, Any]:
```
* **Async:** False
* **Method:** False
* **Class:** N/A
