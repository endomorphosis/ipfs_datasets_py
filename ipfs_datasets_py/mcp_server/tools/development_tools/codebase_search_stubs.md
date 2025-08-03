# Function and Class stubs from '/home/kylerose1946/ipfs_datasets_py/ipfs_datasets_py/mcp_server/tools/development_tools/codebase_search.py'

Files last updated: 1748635923.4413795

Stub file last updated: 2025-07-07 02:47:23

## CodebaseSearchEngine

```python
class CodebaseSearchEngine:
    """
    Advanced codebase search engine with pattern matching, filtering, and analysis.

Features:
- Regular expression and literal pattern matching
- File extension and path filtering
- Context lines around matches
- Multiple output formats (text, JSON, XML)
- Performance optimization with parallel processing
- Dataset-aware search for IPFS hashes and data science patterns
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## CodebaseSearchResult

```python
@dataclass
class CodebaseSearchResult:
    """
    Complete codebase search results.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## FileSearchResult

```python
@dataclass
class FileSearchResult:
    """
    Represents search results for a single file.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## SearchMatch

```python
@dataclass
class SearchMatch:
    """
    Represents a single search match.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## SearchSummary

```python
@dataclass
class SearchSummary:
    """
    Summary of search operation.
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
* **Class:** CodebaseSearchEngine

## _compile_search_pattern

```python
def _compile_search_pattern(self, pattern: str, case_insensitive: bool, whole_word: bool, regex: bool) -> re.Pattern:
    """
    Compile search pattern with specified options.
    """
```
* **Async:** False
* **Method:** True
* **Class:** CodebaseSearchEngine

## _execute_core

```python
async def _execute_core(self, **kwargs) -> Dict[str, Any]:
    """
    Core execution method for the codebase search tool.

Args:
    **kwargs: Search parameters

Returns:
    Standardized result dictionary
    """
```
* **Async:** True
* **Method:** True
* **Class:** CodebaseSearchEngine

## _find_files

```python
def _find_files(self, search_path: Path, extensions: Optional[List[str]], exclude_patterns: List[str], max_depth: Optional[int]) -> List[Path]:
    """
    Find all files to search based on criteria.
    """
```
* **Async:** False
* **Method:** True
* **Class:** CodebaseSearchEngine

## _format_grouped_results

```python
def _format_grouped_results(self, file_results: List[FileSearchResult], compact: bool) -> List[str]:
    """
    Format results grouped by file.
    """
```
* **Async:** False
* **Method:** True
* **Class:** CodebaseSearchEngine

## _format_sequential_results

```python
def _format_sequential_results(self, file_results: List[FileSearchResult], compact: bool) -> List[str]:
    """
    Format results in sequential order.
    """
```
* **Async:** False
* **Method:** True
* **Class:** CodebaseSearchEngine

## _format_text

```python
def _format_text(self, results: CodebaseSearchResult, compact: bool, group_by_file: bool) -> str:
    """
    Format results as human-readable text.
    """
```
* **Async:** False
* **Method:** True
* **Class:** CodebaseSearchEngine

## _format_xml

```python
def _format_xml(self, results: CodebaseSearchResult) -> str:
    """
    Format results as XML.
    """
```
* **Async:** False
* **Method:** True
* **Class:** CodebaseSearchEngine

## _get_file_encoding

```python
def _get_file_encoding(self, file_path: Path) -> str:
    """
    Detect file encoding.
    """
```
* **Async:** False
* **Method:** True
* **Class:** CodebaseSearchEngine

## _search_file

```python
def _search_file(self, file_path: Path, compiled_pattern: re.Pattern, context_lines: int) -> Optional[FileSearchResult]:
    """
    Search a single file for the pattern.
    """
```
* **Async:** False
* **Method:** True
* **Class:** CodebaseSearchEngine

## _should_exclude_file

```python
def _should_exclude_file(self, file_path: str, exclude_patterns: List[str]) -> bool:
    """
    Check if file should be excluded based on patterns.
    """
```
* **Async:** False
* **Method:** True
* **Class:** CodebaseSearchEngine

## _should_include_file

```python
def _should_include_file(self, file_path: Path, extensions: Optional[List[str]]) -> bool:
    """
    Check if file should be included based on extension filter.
    """
```
* **Async:** False
* **Method:** True
* **Class:** CodebaseSearchEngine

## codebase_search

```python
def codebase_search(pattern: str, path: str = ".", case_insensitive: bool = False, whole_word: bool = False, regex: bool = False, extensions: Optional[str] = None, exclude: Optional[str] = None, max_depth: Optional[int] = None, context: int = 0, format: str = "text", output: Optional[str] = None, compact: bool = False, group_by_file: bool = False, summary: bool = False) -> Union[str, Dict[str, Any]]:
    """
    Search codebase for patterns with structured output.

This tool provides advanced pattern matching and code search functionality
with support for regular expressions, file filtering, context lines, and
multiple output formats. Enhanced with dataset-aware capabilities.

Args:
    pattern: The pattern to search for
    path: The path to search in. Defaults to current directory
    case_insensitive: Perform case-insensitive search
    whole_word: Match whole words only
    regex: Interpret pattern as a regular expression
    extensions: Comma-separated list of file extensions to search (e.g., 'py,txt')
    exclude: Comma-separated list of glob patterns to exclude
    max_depth: Maximum directory depth to search
    context: Number of lines of context to include before and after matches
    format: Output format (text, json, xml, dict)
    output: Write output to file instead of returning string
    compact: Use compact output format (one line per match)
    group_by_file: Group results by file
    summary: Include summary information in output

Returns:
    Formatted search results or standardized dict result
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## format_results

```python
def format_results(self, results: CodebaseSearchResult, format_type: str = "text", compact: bool = False, group_by_file: bool = False) -> str:
    """
    Format search results in the specified format.

Args:
    results: The search results to format
    format_type: Output format ('text', 'json', 'xml')
    compact: Use compact output format
    group_by_file: Group results by file

Returns:
    Formatted string representation of results
    """
```
* **Async:** False
* **Method:** True
* **Class:** CodebaseSearchEngine

## process_directory

```python
def process_directory(dir_path: Path, current_depth: int = 0):
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## search_codebase

```python
def search_codebase(self, pattern: str, path: str = ".", case_insensitive: bool = False, whole_word: bool = False, regex: bool = False, extensions: Optional[str] = None, exclude: Optional[str] = None, max_depth: Optional[int] = None, context: int = 0, max_workers: int = 4) -> CodebaseSearchResult:
    """
    Search codebase for patterns with advanced filtering and analysis.

Args:
    pattern: The pattern to search for
    path: The path to search in
    case_insensitive: Perform case-insensitive search
    whole_word: Match whole words only
    regex: Interpret pattern as regular expression
    extensions: Comma-separated list of file extensions to search
    exclude: Comma-separated list of glob patterns to exclude
    max_depth: Maximum directory depth to search
    context: Number of lines of context around matches
    max_workers: Number of parallel workers for file processing

Returns:
    CodebaseSearchResult containing all search results and metadata
    """
```
* **Async:** False
* **Method:** True
* **Class:** CodebaseSearchEngine

## search_dataset_patterns

```python
def search_dataset_patterns(self, path: str = ".", pattern_type: str = "all") -> Dict[str, Any]:
    """
    Search for dataset-specific patterns (IPFS hashes, ML patterns, etc.).

Args:
    path: Path to search
    pattern_type: Type of patterns to search for

Returns:
    Dictionary containing found patterns organized by type
    """
```
* **Async:** False
* **Method:** True
* **Class:** CodebaseSearchEngine

## should_process_dir

```python
def should_process_dir(dir_path: Path, current_depth: int) -> bool:
```
* **Async:** False
* **Method:** False
* **Class:** N/A
