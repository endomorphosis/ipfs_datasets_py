# Function and Class stubs from '<repo-root>/ipfs_datasets_py/ipfs_datasets_py/mcp_server/tools/development_tools/linting_tools.py'

Files last updated: 1751408933.6964564

Stub file last updated: 2025-07-07 02:47:23

## DatasetLinter

```python
class DatasetLinter:
    """
    Specialized linting for dataset-related code.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## LintIssue

```python
@dataclass
class LintIssue:
    """
    Represents a linting issue.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## LintResult

```python
@dataclass
class LintResult:
    """
    Results of linting operation.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## LintingTools

```python
class LintingTools(BaseDevelopmentTool):
    """
    Comprehensive linting tools for Python projects.

Provides code quality checks, formatting fixes, and dataset-specific validations
with support for flake8, mypy, and custom rules.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## PythonLinter

```python
class PythonLinter:
    """
    Core Python linting functionality.
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
* **Class:** PythonLinter

## __init__

```python
def __init__(self):
```
* **Async:** False
* **Method:** True
* **Class:** DatasetLinter

## __init__

```python
def __init__(self):
```
* **Async:** False
* **Method:** True
* **Class:** LintingTools

## _aggregate_results

```python
def _aggregate_results(self, lint_results: List[LintResult]) -> Dict[str, Any]:
    """
    Aggregate results from multiple files.
    """
```
* **Async:** False
* **Method:** True
* **Class:** LintingTools

## _apply_basic_fixes

```python
def _apply_basic_fixes(self, content: str, file_path: Path) -> Tuple[str, List[LintIssue]]:
    """
    Apply basic formatting fixes.
    """
```
* **Async:** False
* **Method:** True
* **Class:** PythonLinter

## _create_summary

```python
def _create_summary(self, issues: List[LintIssue]) -> Dict[str, Any]:
    """
    Create summary of linting results.
    """
```
* **Async:** False
* **Method:** True
* **Class:** PythonLinter

## _discover_python_files

```python
def _discover_python_files(self, path: Path, patterns: List[str], exclude_patterns: List[str]) -> List[Path]:
    """
    Discover Python files to lint.
    """
```
* **Async:** False
* **Method:** True
* **Class:** LintingTools

## _execute_core

```python
async def _execute_core(self, **kwargs) -> Dict[str, Any]:
    """
    Core execution logic for the linting tools.

Args:
    **kwargs: Tool-specific parameters forwarded to lint_codebase

Returns:
    Tool execution result
    """
```
* **Async:** True
* **Method:** True
* **Class:** LintingTools

## _has_error_handling_nearby

```python
def _has_error_handling_nearby(self, lines: List[str], line_index: int) -> bool:
    """
    Check if error handling exists near the given line.
    """
```
* **Async:** False
* **Method:** True
* **Class:** DatasetLinter

## _lint_files_parallel

```python
async def _lint_files_parallel(self, python_files: List[Path], fix_issues: bool, include_dataset_rules: bool, verbose: bool) -> List[LintResult]:
    """
    Lint Python files in parallel.
    """
```
* **Async:** True
* **Method:** True
* **Class:** LintingTools

## _run_external_linters

```python
def _run_external_linters(self, file_path: Path) -> List[LintIssue]:
    """
    Run external linting tools.
    """
```
* **Async:** False
* **Method:** True
* **Class:** PythonLinter

## _run_flake8

```python
def _run_flake8(self, file_path: Path) -> List[LintIssue]:
    """
    Run flake8 linter.
    """
```
* **Async:** False
* **Method:** True
* **Class:** PythonLinter

## _run_mypy

```python
def _run_mypy(self, file_path: Path) -> List[LintIssue]:
    """
    Run mypy type checker.
    """
```
* **Async:** False
* **Method:** True
* **Class:** PythonLinter

## _should_include_file

```python
def _should_include_file(self, file_path: Path, exclude_patterns: List[str]) -> bool:
    """
    Check if file should be included based on exclude patterns.
    """
```
* **Async:** False
* **Method:** True
* **Class:** LintingTools

## lint_codebase

```python
async def lint_codebase(self, path: str = ".", patterns: Optional[List[str]] = None, exclude_patterns: Optional[List[str]] = None, fix_issues: bool = True, include_dataset_rules: bool = True, dry_run: bool = False, verbose: bool = False) -> Dict[str, Any]:
    """
    Lint Python codebase with comprehensive quality checks.

Args:
    path: Target directory to process (default: ".")
    patterns: File patterns to include (default: ['**/*.py'])
    exclude_patterns: Patterns to exclude (default: configured defaults)
    fix_issues: Apply automatic fixes where possible (default: True)
    include_dataset_rules: Include dataset-specific linting rules (default: True)
    dry_run: Show what would be changed without making changes (default: False)
    verbose: Print detailed information (default: False)

Returns:
    Dictionary containing linting results and statistics
    """
```
* **Async:** True
* **Method:** True
* **Class:** LintingTools

## lint_dataset_code

```python
def lint_dataset_code(self, file_path: Path) -> List[LintIssue]:
    """
    Apply dataset-specific linting rules.
    """
```
* **Async:** False
* **Method:** True
* **Class:** DatasetLinter

## lint_file

```python
def lint_file(self, file_path: Path, fix_issues: bool = True, patterns: Optional[List[str]] = None) -> LintResult:
    """
    Lint a single Python file.
    """
```
* **Async:** False
* **Method:** True
* **Class:** PythonLinter

## lint_file_sync

```python
def lint_file_sync(file_path):
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## lint_python_codebase

```python
def lint_python_codebase(path: str = ".", patterns: Optional[List[str]] = None, exclude_patterns: Optional[List[str]] = None, fix_issues: bool = True, include_dataset_rules: bool = True, dry_run: bool = False, verbose: bool = False) -> Dict[str, Any]:
    """
    Lint Python codebase with comprehensive quality checks and automatic fixes.

Args:
    path: Target directory to process (default: ".")
    patterns: File patterns to include like ['**/*.py'] (default: None uses config)
    exclude_patterns: Patterns to exclude like ['.venv', '__pycache__'] (default: None uses config)
    fix_issues: Apply automatic fixes where possible (default: True)
    include_dataset_rules: Include dataset-specific linting rules (default: True)
    dry_run: Show what would be changed without making changes (default: False)
    verbose: Print detailed information for each file (default: False)

Returns:
    Dictionary containing linting results, statistics, and issue details
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## linting_tools

```python
async def linting_tools(path: str = ".", file_patterns: Optional[List[str]] = None, auto_fix: bool = False, exclude_dirs: Optional[List[str]] = None):
    """
    Comprehensive Python code linting and auto-fixing.
    """
```
* **Async:** True
* **Method:** False
* **Class:** N/A

## run_in_thread

```python
def run_in_thread():
```
* **Async:** False
* **Method:** False
* **Class:** N/A
