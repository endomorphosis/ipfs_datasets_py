# Function and Class stubs from '/home/kylerose1946/omni_converter_mk2/monitors/security_monitor/_security_result.py'

Files last updated: 1750499454.0042183

Stub file last updated: 2025-07-17 05:28:52

## RiskLevel

```python
class RiskLevel(str, Enum):
    """
    Enumeration for risk levels.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## SecurityResult

```python
class SecurityResult(BaseModel):
    """
    Result of security validation.

This class represents the result of security validation for a file.

Attributes:
    is_safe (bool): Whether the file is considered safe.
    issues (list[str]): list of security issues found.
    risk_level (str): Risk level assessment ('low', 'medium', 'high'). Default is 'low'. # TODO Maybe this should be high as default?
    metadata (dict[str, Any]): Additional metadata about the security check.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## __str__

```python
def __str__(self) -> str:
    """
    Return the string representation of the risk level.
    """
```
* **Async:** False
* **Method:** True
* **Class:** RiskLevel

## to_dict

```python
def to_dict(self) -> dict[str, Any]:
    """
    Convert to a dictionary.

Returns:
    A dictionary representation of the security result.
    """
```
* **Async:** False
* **Method:** True
* **Class:** SecurityResult
