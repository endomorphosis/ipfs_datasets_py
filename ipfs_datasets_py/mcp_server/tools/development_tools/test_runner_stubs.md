# Function and Class stubs from '<repo-root>/ipfs_datasets_py/ipfs_datasets_py/mcp_server/tools/development_tools/test_runner.py'

Files last updated: 1751763370.0639503

Stub file last updated: 2025-07-07 02:47:23

## DatasetTestRunner

```python
class DatasetTestRunner:
    """
    Specialized test runner for dataset-related functionality.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## TestExecutor

```python
class TestExecutor:
    """
    Core test execution functionality.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## TestResult

```python
@dataclass
class TestResult:
    """
    Individual test result.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## TestRunSummary

```python
@dataclass
class TestRunSummary:
    """
    Complete test run summary.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## TestRunner

```python
class TestRunner(BaseDevelopmentTool):
    """
    Comprehensive test runner for Python projects.

Executes unit tests, type checking, linting, and dataset integrity tests
with detailed reporting and results export.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## TestSuiteResult

```python
@dataclass
class TestSuiteResult:
    """
    Results from a test suite run.
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
* **Class:** TestExecutor

## __init__

```python
def __init__(self):
```
* **Async:** False
* **Method:** True
* **Class:** DatasetTestRunner

## __init__

```python
def __init__(self):
```
* **Async:** False
* **Method:** True
* **Class:** TestRunner

## __post_init__

```python
def __post_init__(self):
```
* **Async:** False
* **Method:** True
* **Class:** TestSuiteResult

## __post_init__

```python
def __post_init__(self):
```
* **Async:** False
* **Method:** True
* **Class:** TestRunSummary

## _execute_core

```python
async def _execute_core(self, **kwargs) -> Dict[str, Any]:
    """
    Core execution logic for the test runner.

Args:
    **kwargs: Tool-specific parameters forwarded to run_comprehensive_tests

Returns:
    Tool execution result
    """
```
* **Async:** True
* **Method:** True
* **Class:** TestRunner

## _generate_markdown_report

```python
def _generate_markdown_report(self, summary: TestRunSummary) -> str:
    """
    Generate markdown test report.
    """
```
* **Async:** False
* **Method:** True
* **Class:** TestRunner

## _parse_dataset_test_output

```python
def _parse_dataset_test_output(self, output: str) -> Tuple[int, int, int, int, int]:
    """
    Parse dataset test output.
    """
```
* **Async:** False
* **Method:** True
* **Class:** DatasetTestRunner

## _parse_pytest_output

```python
def _parse_pytest_output(self, output: str) -> Tuple[int, int, int, int, int]:
    """
    Parse pytest output for test counts.
    """
```
* **Async:** False
* **Method:** True
* **Class:** TestExecutor

## _parse_unittest_output

```python
def _parse_unittest_output(self, output: str) -> Tuple[int, int, int, int, int]:
    """
    Parse unittest output for test counts.
    """
```
* **Async:** False
* **Method:** True
* **Class:** TestExecutor

## _run_test_suite_async

```python
async def _run_test_suite_async(self, suite_type: str, path: Path, coverage: bool = False, verbose: bool = False) -> TestSuiteResult:
    """
    Run a test suite asynchronously.
    """
```
* **Async:** True
* **Method:** True
* **Class:** TestRunner

## _save_test_results

```python
async def _save_test_results(self, summary: TestRunSummary, path: Path, formats: List[str]) -> List[str]:
    """
    Save test results in specified formats.
    """
```
* **Async:** True
* **Method:** True
* **Class:** TestRunner

## create_test_runner

```python
def create_test_runner(path: str = ".", run_unit_tests: bool = True, run_type_check: bool = True, run_linting: bool = True, run_dataset_tests: bool = True, test_framework: str = "pytest", coverage: bool = True, verbose: bool = False, save_results: bool = True, output_formats: Optional[List[str]] = None) -> BaseDevelopmentTool:
    """
    Create a properly configured TestRunner instance.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## create_test_runner

```python
async def create_test_runner(path: str = ".", verbose: bool = False, coverage: bool = True, run_unit_tests: bool = True, run_type_check: bool = True, run_linting: bool = True, run_dataset_tests: bool = True, test_framework: str = "pytest", save_results: bool = True, output_formats: Optional[List[str]] = None):
    """
    Create a properly configured TestRunner instance.
    """
```
* **Async:** True
* **Method:** False
* **Class:** N/A

## run_comprehensive_tests

```python
async def run_comprehensive_tests(self, path: str = ".", run_unit_tests: bool = True, run_type_check: bool = True, run_linting: bool = True, run_dataset_tests: bool = True, test_framework: str = "pytest", coverage: bool = True, verbose: bool = False, save_results: bool = True, output_formats: Optional[List[str]] = None) -> Dict[str, Any]:
    """
    Run comprehensive test suite with multiple checkers.

Args:
    path: Path to the project directory (default: ".")
    run_unit_tests: Run unit tests (default: True)
    run_type_check: Run mypy type checking (default: True)
    run_linting: Run flake8 linting (default: True)
    run_dataset_tests: Run dataset integrity tests (default: True)
    test_framework: Testing framework to use - 'pytest' or 'unittest' (default: "pytest")
    coverage: Generate coverage report (default: True)
    verbose: Enable verbose output (default: False)
    save_results: Save results to files (default: True)
    output_formats: Output formats for results - ['json', 'markdown'] (default: ['json'])

Returns:
    Dictionary containing comprehensive test results and statistics
    """
```
* **Async:** True
* **Method:** True
* **Class:** TestRunner

## run_comprehensive_tests

```python
@development_tool_mcp_wrapper
def run_comprehensive_tests(path: str = ".", run_unit_tests: bool = True, run_type_check: bool = True, run_linting: bool = True, run_dataset_tests: bool = True, test_framework: str = "pytest", coverage: bool = True, verbose: bool = False, save_results: bool = True, output_formats: Optional[List[str]] = None) -> Dict[str, Any]:
    """
    Run comprehensive test suite including unit tests, type checking, linting, and dataset tests.

Args:
    path: Path to the project directory (default: ".")
    run_unit_tests: Run unit tests (default: True)
    run_type_check: Run mypy type checking (default: True)
    run_linting: Run flake8 linting (default: True)
    run_dataset_tests: Run dataset integrity tests (default: True)
    test_framework: Testing framework - 'pytest' or 'unittest' (default: "pytest")
    coverage: Generate coverage report (default: True)
    verbose: Enable verbose output (default: False)
    save_results: Save results to files (default: True)
    output_formats: Output formats - ['json', 'markdown'] (default: ['json'])

Returns:
    Dict containing test results
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## run_dataset_integrity_tests

```python
def run_dataset_integrity_tests(self, path: Path) -> TestSuiteResult:
    """
    Run dataset integrity and validation tests.
    """
```
* **Async:** False
* **Method:** True
* **Class:** DatasetTestRunner

## run_flake8

```python
def run_flake8(self, path: Path) -> TestSuiteResult:
    """
    Run flake8 linting.
    """
```
* **Async:** False
* **Method:** True
* **Class:** TestExecutor

## run_in_thread

```python
def run_in_thread():
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## run_mypy

```python
def run_mypy(self, path: Path) -> TestSuiteResult:
    """
    Run mypy type checking.
    """
```
* **Async:** False
* **Method:** True
* **Class:** TestExecutor

## run_pytest

```python
def run_pytest(self, path: Path, coverage: bool = True, verbose: bool = False) -> TestSuiteResult:
    """
    Run pytest test suite.
    """
```
* **Async:** False
* **Method:** True
* **Class:** TestExecutor

## run_suite

```python
def run_suite():
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## run_unittest

```python
def run_unittest(self, path: Path, verbose: bool = False) -> TestSuiteResult:
    """
    Run unittest test suite.
    """
```
* **Async:** False
* **Method:** True
* **Class:** TestExecutor

## test_runner

```python
async def test_runner(**kwargs):
    """
    Comprehensive test runner for Python projects.

Executes unit tests, type checking, linting, and dataset integrity tests
with detailed reporting and results export.
    """
```
* **Async:** True
* **Method:** False
* **Class:** N/A
