# Function and Class stubs from '/home/kylerose1946/ipfs_datasets_py/ipfs_datasets_py/mcp_server/tools/development_tools/documentation_generator_simple.py'

Files last updated: 1751408933.6964564

Stub file last updated: 2025-07-07 01:10:13

## documentation_generator

```python
def documentation_generator(input_path: str, output_path: str = "docs", docstring_style: str = "google", ignore_patterns: Optional[List[str]] = None, include_inheritance: bool = True, include_examples: bool = True, include_source_links: bool = True, format_type: str = "markdown") -> Dict[str, Any]:
    """
    Generate comprehensive documentation from Python source code.

Args:
    input_path: Path to Python file or directory to document
    output_path: Directory to save generated documentation (default: "docs")
    docstring_style: Docstring parsing style - 'google', 'numpy', 'rest' (default: "google")
    ignore_patterns: List of glob patterns to ignore (default: None)
    include_inheritance: Include class inheritance information (default: True)
    include_examples: Include code examples in documentation (default: True)
    include_source_links: Include links to source code (default: True)
    format_type: Output format - 'markdown', 'html' (default: "markdown")

Returns:
    Dictionary containing generation results, file paths, and metadata
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## documentation_generator_simple

```python
async def documentation_generator_simple(input_path: str = ".", output_path: str = "docs", docstring_style: str = "google", ignore_patterns: Optional[List[str]] = None, include_inheritance: bool = True, include_examples: bool = True, include_source_links: bool = True, format_type: str = "markdown"):
    """
    Generate comprehensive documentation from Python source code.
Simplified async wrapper for MCP registration.
    """
```
* **Async:** True
* **Method:** False
* **Class:** N/A
