# Function and Class stubs from '/home/kylerose1946/omni_converter_mk2/core/file_validator/_validation_result.py'

## ValidationResult

```python
class ValidationResult(BaseModel):
    """
    Result of validation operations.

This class represents the result of validating a file or content, including
validity status, errors, warnings, and context information.

Attributes:
    is_valid (bool): Whether the validation was successful.
    errors (list[str]): list of errors encountered during validation.
    warnings (list[str]): list of warnings encountered during validation.
    validation_context (dict[str, Any]): Additional context about the validation.
    """
```
## add_context

```python
def add_context(self, key: str, value: Any) -> None:
    """
    Add validation context to the result.

Args:
    key: The context key.
    value: The context value.
    """
```
* **Async:** False
* **Method:** True
* **Class:** ValidationResult

## add_error

```python
def add_error(self, error: str) -> None:
    """
    Add an error to the result.

Args:
    error: The error message to add.
    """
```
* **Async:** False
* **Method:** True
* **Class:** ValidationResult

## add_warning

```python
def add_warning(self, warning: str) -> None:
    """
    Add a warning to the result.

Args:
    warning: The warning message to add.
    """
```
* **Async:** False
* **Method:** True
* **Class:** ValidationResult

## to_dict

```python
def to_dict(self) -> dict[str, Any]:
    """
    Convert to a dictionary.

Returns:
    A dictionary representation of the validation result.
    """
```
* **Async:** False
* **Method:** True
* **Class:** ValidationResult
