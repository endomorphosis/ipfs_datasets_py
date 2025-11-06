# Function and Class stubs from '/home/kylerose1946/ipfs_datasets_py/ipfs_datasets_py/mcp_server/validators.py'

Files last updated: 1751414068.1929781

Stub file last updated: 2025-07-07 02:35:43

## EnhancedParameterValidator

```python
class EnhancedParameterValidator:
    """
    Enhanced parameter validation for production MCP tools.
Provides comprehensive validation for various data types and formats.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## ValidationError

```python
class ValidationError(Exception):
    """
    Custom validation error for MCP tools.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## __init__

```python
def __init__(self, parameter: str, message: str):
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
* **Class:** EnhancedParameterValidator

## _cache_key

```python
def _cache_key(self, value: Any, validation_type: str) -> str:
    """
    Generate cache key for validation result.
    """
```
* **Async:** False
* **Method:** True
* **Class:** EnhancedParameterValidator

## _contains_suspicious_patterns

```python
def _contains_suspicious_patterns(self, text: str) -> bool:
    """
    Check for potentially suspicious patterns in text.
    """
```
* **Async:** False
* **Method:** True
* **Class:** EnhancedParameterValidator

## clear_cache

```python
def clear_cache(self) -> None:
    """
    Clear validation cache.
    """
```
* **Async:** False
* **Method:** True
* **Class:** EnhancedParameterValidator

## get_performance_metrics

```python
def get_performance_metrics(self) -> Dict[str, int]:
    """
    Get validation performance metrics.
    """
```
* **Async:** False
* **Method:** True
* **Class:** EnhancedParameterValidator

## validate_collection_name

```python
def validate_collection_name(self, collection_name: str) -> str:
    """
    Validate collection name format with enhanced security checks.
    """
```
* **Async:** False
* **Method:** True
* **Class:** EnhancedParameterValidator

## validate_file_path

```python
def validate_file_path(self, file_path: str, check_exists: bool = False, allowed_extensions: Optional[Set[str]] = None) -> str:
    """
    Validate file path format and optionally check existence.
    """
```
* **Async:** False
* **Method:** True
* **Class:** EnhancedParameterValidator

## validate_ipfs_hash

```python
def validate_ipfs_hash(self, ipfs_hash: str) -> str:
    """
    Validate IPFS hash format.
    """
```
* **Async:** False
* **Method:** True
* **Class:** EnhancedParameterValidator

## validate_json_schema

```python
def validate_json_schema(self, data: Any, schema: Dict[str, Any]) -> Any:
    """
    Validate data against JSON schema.
    """
```
* **Async:** False
* **Method:** True
* **Class:** EnhancedParameterValidator

## validate_model_name

```python
def validate_model_name(self, model_name: str) -> str:
    """
    Validate embedding model name with caching.
    """
```
* **Async:** False
* **Method:** True
* **Class:** EnhancedParameterValidator

## validate_numeric_range

```python
def validate_numeric_range(self, value: Union[int, float], param_name: str, min_val: Optional[float] = None, max_val: Optional[float] = None, allow_none: bool = False) -> Union[int, float, None]:
    """
    Validate numeric value within specified range.
    """
```
* **Async:** False
* **Method:** True
* **Class:** EnhancedParameterValidator

## validate_search_filters

```python
def validate_search_filters(self, filters: Dict[str, Any]) -> Dict[str, Any]:
    """
    Validate search filter parameters with enhanced security.
    """
```
* **Async:** False
* **Method:** True
* **Class:** EnhancedParameterValidator

## validate_text_input

```python
def validate_text_input(self, text: str, max_length: int = 10000, min_length: int = 1, allow_empty: bool = False) -> str:
    """
    Validate text input with length constraints and content checks.
    """
```
* **Async:** False
* **Method:** True
* **Class:** EnhancedParameterValidator

## validate_url

```python
def validate_url(self, url: str, allowed_schemes: Optional[Set[str]] = None) -> str:
    """
    Validate URL format and scheme.
    """
```
* **Async:** False
* **Method:** True
* **Class:** EnhancedParameterValidator
