# Function and Class stubs from '/home/kylerose1946/ipfs_datasets_py/ipfs_datasets_py/mcp_server/tools/development_tools/test_generator.py'

Files last updated: 1751763372.707238

Stub file last updated: 2025-07-07 02:47:23

## TestGeneratorTool

```python
class TestGeneratorTool(BaseDevelopmentTool):
    """
    Tool for generating test files from JSON specifications.

Supports both unittest and pytest frameworks with configurable templates.
Enhanced with dataset-specific test patterns and IPFS integration.
    """
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
* **Class:** TestGeneratorTool

## _enhance_with_dataset_features

```python
def _enhance_with_dataset_features(self, spec: Dict[str, Any]) -> Dict[str, Any]:
    """
    Enhance test specification with dataset-specific features.

Args:
    spec: Base test specification

Returns:
    Enhanced specification with dataset features
    """
```
* **Async:** False
* **Method:** True
* **Class:** TestGeneratorTool

## _execute_core

```python
async def _execute_core(self, **kwargs) -> Dict[str, Any]:
    """
    Core test generation logic.

Args:
    name: Test name
    description: Test description
    test_specification: JSON test specification (str or dict)
    output_dir: Output directory (optional)
    harness: Test harness (unittest/pytest, optional)

Returns:
    Test generation result
    """
```
* **Async:** True
* **Method:** True
* **Class:** TestGeneratorTool

## _generate_class_name

```python
def _generate_class_name(self, name: str) -> str:
    """
    Generate a valid class name from test name.
    """
```
* **Async:** False
* **Method:** True
* **Class:** TestGeneratorTool

## _generate_test_content

```python
def _generate_test_content(self, spec: Dict[str, Any]) -> str:
    """
    Generate test file content from specification.

Args:
    spec: Parsed test specification

Returns:
    Generated test file content
    """
```
* **Async:** False
* **Method:** True
* **Class:** TestGeneratorTool

## _get_pytest_template

```python
def _get_pytest_template(self) -> str:
    """
    Get the pytest template string.
    """
```
* **Async:** False
* **Method:** True
* **Class:** TestGeneratorTool

## _get_unittest_template

```python
def _get_unittest_template(self) -> str:
    """
    Get the unittest template string.
    """
```
* **Async:** False
* **Method:** True
* **Class:** TestGeneratorTool

## _parse_test_specification

```python
def _parse_test_specification(self, test_spec: Union[str, Dict[str, Any]]) -> Dict[str, Any]:
    """
    Parse test specification from JSON string or dict.

Args:
    test_spec: Test specification as JSON string or dict

Returns:
    Parsed test specification dictionary
    """
```
* **Async:** False
* **Method:** True
* **Class:** TestGeneratorTool

## run_in_thread

```python
def run_in_thread():
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## test_generator

```python
def test_generator(name: str, description: str = "", test_specification: Union[str, Dict[str, Any]] = None, output_dir: str = None, harness: str = None) -> Dict[str, Any]:
    """
    Generate test files from JSON specifications.

Args:
    name: Name of the test suite
    description: Description of what the tests cover
    test_specification: JSON specification as string or dict containing test definitions
    output_dir: Directory to output test files (defaults to config setting)
    harness: Test framework to use - 'unittest' or 'pytest' (defaults to config setting)

Returns:
    Dict containing generation results and metadata

Example test_specification:
{
    "imports": ["import requests", "from mymodule import MyClass"],
    "fixtures": [
        {"name": "sample_data", "value": "{'key': 'value'}"}
    ],
    "tests": [
        {
            "name": "example_test",
            "description": "Test example functionality",
            "assertions": ["self.assertEqual(1, 1)", "self.assertTrue(True)"],
            "parametrized": false
        }
    ]
}
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A
