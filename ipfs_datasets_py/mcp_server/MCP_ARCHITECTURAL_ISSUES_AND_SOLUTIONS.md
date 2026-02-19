# MCP Server Architectural Issues and Solutions

**Date:** 2026-02-19  
**Status:** Analysis Complete  
**Priority:** HIGH

---

## Executive Summary

This document provides a detailed analysis of the top 10 architectural and code quality issues found in the MCP server codebase, along with concrete solutions and implementation plans. These issues were identified through comprehensive code review, static analysis, and testing gaps analysis.

### Issue Categories

- **🔴 CRITICAL (5 issues):** Must fix immediately - impacts stability, correctness, or security
- **🟡 HIGH (3 issues):** Should fix soon - impacts maintainability and performance
- **🟢 MEDIUM (2 issues):** Nice to have - improves code quality

---

## Table of Contents

1. [Issue #1: Complex Function - _get_hierarchical_tools](#issue-1-complex-function---_get_hierarchical_tools)
2. [Issue #2: Bare Exception Handlers](#issue-2-bare-exception-handlers)
3. [Issue #3: Missing Error Handling on Imports](#issue-3-missing-error-handling-on-imports)
4. [Issue #4: Type Hint Inconsistencies](#issue-4-type-hint-inconsistencies)
5. [Issue #5: Closure Variable Capture Bug](#issue-5-closure-variable-capture-bug)
6. [Issue #6: Missing Docstrings on Public APIs](#issue-6-missing-docstrings-on-public-apis)
7. [Issue #7: Complex Import Error Handling](#issue-7-complex-import-error-handling)
8. [Issue #8: Async/Sync Pattern Inconsistency](#issue-8-asyncsync-pattern-inconsistency)
9. [Issue #9: Missing Input Validation](#issue-9-missing-input-validation)
10. [Issue #10: asyncio.run() in Running Event Loop](#issue-10-asynciorun-in-running-event-loop)

---

## Issue #1: Complex Function - _get_hierarchical_tools

### 🔴 CRITICAL - High Complexity (114 lines, 7+ nested blocks)

**Location:** `p2p_mcp_registry_adapter.py:126-240`

**Problem Description:**
The `_get_hierarchical_tools` method is a 114-line function with:
- 7+ nested try-except blocks
- Multiple `asyncio.run()` calls (lines 162, 177)
- Closure variable capture bug (lines 194-206)
- Multiple bare `except Exception` blocks (lines 148-228)
- High cyclomatic complexity (estimated 15-20)

**Impact:**
- **Maintainability:** Extremely difficult to understand and modify
- **Testability:** Cannot test individual logic blocks in isolation
- **Correctness:** Closure bug causes all wrappers to reference last category
- **Reliability:** Event loop issues cause RuntimeError in async contexts

**Current Code Pattern:**
```python
def _get_hierarchical_tools(self) -> dict[str, dict[str, Callable]]:
    """114-line monolithic function."""
    result = {}
    
    # Lines 130-160: Category discovery with nested try-except
    try:
        tool_manager = self._get_tool_manager()
        try:
            tools = asyncio.run(tool_manager.list_tools())  # Line 162 - BUG!
            # ...nested logic...
        except Exception as e:  # Bare exception
            # ...error handling...
    except Exception as e:  # Another bare exception
        # ...more error handling...
    
    # Lines 165-190: Tool loading with more nested try-except
    for cat in categories:
        try:
            cat_tools = asyncio.run(self._load_category(cat))  # Line 177 - BUG!
            # ...more nested logic...
        except Exception as e:  # Bare exception
            pass
    
    # Lines 194-206: Wrapper creation with closure bug
    for cat in categories:
        for name, func in tools.items():
            def wrapper(*args, **kwargs):
                # BUG: 'cat' is captured from loop, references last value
                return self._execute_tool(cat, name, func, *args, **kwargs)
            result[cat][name] = wrapper
    
    return result
```

### Solution

**Refactoring Strategy:** Extract into 4 focused functions

#### New Function 1: _discover_categories (30 lines)
```python
async def _discover_categories(self) -> List[str]:
    """
    Discover available tool categories.
    
    Returns:
        List of category names (e.g., ["dataset_tools", "ipfs_tools"])
    
    Raises:
        ToolDiscoveryError: If category discovery fails
    """
    try:
        tool_manager = self._get_tool_manager()
        if tool_manager is None:
            logger.warning("Tool manager not available, using empty category list")
            return []
        
        # Get categories from tool manager
        if hasattr(tool_manager, 'get_categories'):
            categories = await tool_manager.get_categories()
        else:
            # Fallback: scan tools directory
            categories = await self._scan_tool_directories()
        
        logger.info(f"Discovered {len(categories)} tool categories")
        return categories
    
    except (ImportError, AttributeError) as e:
        logger.error(f"Failed to discover categories: {e}", exc_info=True)
        raise ToolDiscoveryError(f"Category discovery failed: {e}") from e
```

#### New Function 2: _load_category_tools (35 lines)
```python
async def _load_category_tools(self, category: str) -> Dict[str, Callable]:
    """
    Load all tools from a specific category.
    
    Args:
        category: Category name (e.g., "dataset_tools")
    
    Returns:
        Dictionary mapping tool names to callables
    
    Raises:
        ToolLoadError: If category loading fails
    """
    try:
        tool_manager = self._get_tool_manager()
        if tool_manager is None:
            return {}
        
        # Load tools from category
        if hasattr(tool_manager, 'get_category_tools'):
            tools = await tool_manager.get_category_tools(category)
        else:
            # Fallback: import category module
            tools = await self._import_category_module(category)
        
        logger.debug(f"Loaded {len(tools)} tools from category '{category}'")
        return tools
    
    except ImportError as e:
        logger.warning(f"Category '{category}' not available: {e}")
        return {}  # Graceful degradation
    
    except Exception as e:
        logger.error(f"Failed to load category '{category}': {e}", exc_info=True)
        raise ToolLoadError(f"Failed to load category '{category}': {e}") from e
```

#### New Function 3: _create_tool_wrapper (25 lines)
```python
def _create_tool_wrapper(
    self, 
    category: str, 
    tool_name: str, 
    tool_func: Callable
) -> Callable:
    """
    Create an MCP tool wrapper for a category tool.
    
    Args:
        category: Category name
        tool_name: Tool name within category
        tool_func: The actual tool function
    
    Returns:
        MCP-compatible tool wrapper
    
    Note:
        Uses explicit parameter binding to avoid closure capture bugs.
    """
    from functools import wraps, partial
    
    # Fix closure bug: Use partial for explicit binding
    wrapper = partial(self._execute_tool, category, tool_name, tool_func)
    
    # Preserve function metadata
    wrapper.__name__ = f"{category}_{tool_name}"
    wrapper.__doc__ = tool_func.__doc__ or f"Execute {tool_name} from {category}"
    
    return wrapper
```

#### New Function 4: _validate_tool (20 lines)
```python
def _validate_tool(self, tool_name: str, tool_func: Callable) -> bool:
    """
    Validate that a tool function meets MCP requirements.
    
    Args:
        tool_name: Name of the tool
        tool_func: Tool function to validate
    
    Returns:
        True if tool is valid, False otherwise
    """
    if not callable(tool_func):
        logger.warning(f"Tool '{tool_name}' is not callable")
        return False
    
    if not hasattr(tool_func, '__name__'):
        logger.warning(f"Tool '{tool_name}' missing __name__ attribute")
        return False
    
    # Additional validation checks can be added here
    return True
```

#### Refactored Main Function (40 lines)
```python
async def _get_hierarchical_tools(self) -> Dict[str, Dict[str, Callable]]:
    """
    Get hierarchical tool structure from HierarchicalToolManager.
    
    Returns:
        Nested dictionary: {category: {tool_name: wrapper_func}}
    
    Raises:
        ToolDiscoveryError: If tool discovery fails critically
    """
    result: Dict[str, Dict[str, Callable]] = {}
    
    try:
        # Step 1: Discover categories
        categories = await self._discover_categories()
        
        # Step 2: Load tools from each category
        for category in categories:
            try:
                tools = await self._load_category_tools(category)
                
                # Step 3: Create wrappers for valid tools
                result[category] = {}
                for tool_name, tool_func in tools.items():
                    if self._validate_tool(tool_name, tool_func):
                        wrapper = self._create_tool_wrapper(category, tool_name, tool_func)
                        result[category][tool_name] = wrapper
                
            except ToolLoadError as e:
                # Log but continue with other categories
                logger.error(f"Failed to load category '{category}': {e}")
                continue
        
        logger.info(f"Loaded {sum(len(t) for t in result.values())} tools from "
                   f"{len(result)} categories")
        return result
    
    except ToolDiscoveryError:
        raise  # Re-raise critical errors
    except Exception as e:
        logger.error(f"Unexpected error in tool discovery: {e}", exc_info=True)
        raise ToolDiscoveryError(f"Tool discovery failed unexpectedly: {e}") from e
```

### Implementation Plan

**Effort:** 4-6 hours

**Steps:**
1. Create custom exception classes (`ToolDiscoveryError`, `ToolLoadError`)
2. Implement 4 helper functions with full docstrings
3. Refactor main function to use helpers
4. Write 15 comprehensive unit tests:
   - `test_discover_categories_success` (3 tests)
   - `test_discover_categories_failure` (2 tests)
   - `test_load_category_tools_success` (3 tests)
   - `test_load_category_tools_failure` (2 tests)
   - `test_create_tool_wrapper` (3 tests)
   - `test_validate_tool` (2 tests)
5. Integration test for complete flow
6. Update documentation

**Benefits:**
- ✅ Reduced complexity: 114 lines → 40 lines main + 4 helpers (~30 lines each)
- ✅ Testable: Each function can be tested independently
- ✅ Fixed closure bug: Using `functools.partial`
- ✅ Fixed event loop bug: Proper async/await pattern
- ✅ Better error handling: Specific exception types
- ✅ Improved maintainability: Clear separation of concerns

---

## Issue #2: Bare Exception Handlers

### 🔴 CRITICAL - Masks Errors (10+ instances)

**Locations:**
- `p2p_mcp_registry_adapter.py` (lines 148-159, 175-228, 222-224, 226-228)
- Various tool files

**Problem Description:**
Multiple locations use `except Exception as e:` which catches all exceptions including:
- `KeyboardInterrupt` (should never be caught)
- `SystemExit` (should never be caught)
- `BaseException` subclasses that indicate critical issues

**Impact:**
- **Debugging:** Makes debugging nearly impossible (silent failures)
- **Reliability:** Masks critical errors that should propagate
- **Correctness:** Wrong assumptions about error conditions
- **User Experience:** No clear error messages for users

**Current Anti-Pattern:**
```python
try:
    risky_operation()
except Exception as e:
    logger.error(f"Error: {e}")  # What kind of error?
    return None  # Silent failure - caller doesn't know what happened
```

### Solution

**Exception Hierarchy Strategy:**

```python
# Define domain-specific exception hierarchy
class MCPServerError(Exception):
    """Base exception for MCP server errors."""
    pass

class ToolExecutionError(MCPServerError):
    """Error during tool execution."""
    pass

class ToolRegistrationError(MCPServerError):
    """Error during tool registration."""
    pass

class ValidationError(MCPServerError):
    """Error during parameter validation."""
    pass

class ConfigurationError(MCPServerError):
    """Error in configuration."""
    pass
```

**Exception Handling Patterns:**

#### Pattern 1: I/O Operations
```python
import errno

try:
    with open(file_path, 'r') as f:
        content = f.read()
except FileNotFoundError as e:
    logger.error(f"File not found: {file_path}", exc_info=True)
    raise ToolExecutionError(f"Required file not found: {file_path}") from e
except PermissionError as e:
    logger.error(f"Permission denied: {file_path}", exc_info=True)
    raise ToolExecutionError(f"Cannot read file: {file_path}") from e
except OSError as e:
    if e.errno == errno.ENOSPC:
        logger.critical(f"Disk full while reading: {file_path}")
    raise ToolExecutionError(f"I/O error reading {file_path}: {e}") from e
```

#### Pattern 2: Network Operations
```python
import httpx
import requests

try:
    response = httpx.get(url, timeout=30.0)
    response.raise_for_status()
except httpx.TimeoutException as e:
    logger.warning(f"Request timeout: {url}")
    raise ToolExecutionError(f"Request timed out: {url}") from e
except httpx.HTTPStatusError as e:
    logger.error(f"HTTP error {e.response.status_code}: {url}")
    raise ToolExecutionError(f"HTTP {e.response.status_code}: {url}") from e
except httpx.RequestError as e:
    logger.error(f"Network error: {e}", exc_info=True)
    raise ToolExecutionError(f"Network error: {e}") from e
```

#### Pattern 3: Import Operations
```python
try:
    from optional_dependency import feature
except ImportError as e:
    logger.info(f"Optional dependency not available: {e}")
    # Graceful degradation
    def feature(*args, **kwargs):
        raise ToolExecutionError(
            "This feature requires 'optional_dependency'. "
            "Install with: pip install optional_dependency"
        )
except Exception as e:
    # Only for truly unexpected errors
    logger.error(f"Unexpected import error: {e}", exc_info=True)
    raise
```

#### Pattern 4: Validation Operations
```python
def validate_parameters(params: dict) -> dict:
    """Validate and normalize parameters."""
    try:
        # Use Pydantic or custom validation
        validated = ParamSchema(**params)
        return validated.dict()
    except (ValueError, KeyError, TypeError) as e:
        logger.warning(f"Invalid parameters: {e}")
        raise ValidationError(f"Parameter validation failed: {e}") from e
    # NO except Exception - let unexpected errors propagate
```

#### Pattern 5: Resource Cleanup
```python
from contextlib import contextmanager

@contextmanager
def managed_resource():
    """Context manager with specific exception handling."""
    resource = acquire_resource()
    try:
        yield resource
    except (IOError, OSError) as e:
        logger.error(f"Resource error: {e}", exc_info=True)
        raise ToolExecutionError(f"Resource operation failed: {e}") from e
    finally:
        # Cleanup always happens
        try:
            resource.close()
        except Exception as e:
            logger.warning(f"Cleanup error (non-fatal): {e}")
```

### Implementation Plan

**Effort:** 3-4 hours

**Steps:**
1. Create exception hierarchy in `exceptions.py` (1 hour)
2. Audit all `except Exception` blocks (~10+ instances) (1 hour)
3. Replace with specific exception types (1 hour)
4. Add proper error logging with `exc_info=True` (30 min)
5. Write 8 error handling tests (30 min)

**Tests:**
```python
def test_file_not_found_error():
    """Test FileNotFoundError is caught and converted."""
    with pytest.raises(ToolExecutionError, match="Required file not found"):
        tool.process_file("/nonexistent/file.txt")

def test_network_timeout_error():
    """Test network timeout is handled properly."""
    with pytest.raises(ToolExecutionError, match="Request timed out"):
        tool.fetch_url("http://slow-server.com")

def test_validation_error():
    """Test validation errors are caught."""
    with pytest.raises(ValidationError, match="Parameter validation failed"):
        tool.execute({"invalid": "params"})
```

---

## Issue #3: Missing Error Handling on Imports

### 🔴 CRITICAL - Silent Import Failures

**Location:** `fastapi_service.py:402-410`

**Problem Description:**
The `generate_embeddings_api` endpoint imports tools but doesn't validate if imports succeed. If the import fails (missing dependency, import error), the endpoint will return a 500 error with no clear indication of the problem.

**Current Code:**
```python
@app.post("/embeddings/generate")
async def generate_embeddings_api(request: EmbeddingRequest):
    """Generate embeddings endpoint."""
    from .mcp_server.tools.embedding_tools.embedding_generation import generate_embeddings
    
    # What if import fails? No error handling!
    embeddings = await generate_embeddings(request.texts)
    return {"embeddings": embeddings}
```

### Solution

**Import Validation Pattern:**

```python
# At module level: Try import with fallback
try:
    from .mcp_server.tools.embedding_tools.embedding_generation import generate_embeddings
    EMBEDDINGS_AVAILABLE = True
except ImportError as e:
    logger.warning(f"Embeddings tool not available: {e}")
    EMBEDDINGS_AVAILABLE = False
    generate_embeddings = None

@app.post("/embeddings/generate")
async def generate_embeddings_api(request: EmbeddingRequest):
    """
    Generate embeddings for input texts.
    
    Requires: sentence-transformers, torch
    """
    if not EMBEDDINGS_AVAILABLE:
        raise HTTPException(
            status_code=503,
            detail={
                "error": "Embeddings feature not available",
                "reason": "Missing required dependencies",
                "install": "pip install sentence-transformers torch"
            }
        )
    
    try:
        embeddings = await generate_embeddings(
            request.texts,
            batch_size=request.batch_size,
            model=request.model
        )
        return {"embeddings": embeddings, "model": request.model}
    
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"Invalid parameters: {e}")
    except RuntimeError as e:
        logger.error(f"Embedding generation failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Generation failed: {e}")
```

### Implementation Plan

**Effort:** 2-3 hours

**Steps:**
1. Audit all FastAPI endpoints for import issues
2. Add module-level import validation
3. Add feature availability flags
4. Return proper HTTP status codes (503 for unavailable features)
5. Write 6 tests

---

## Issue #4: Type Hint Inconsistencies

### 🟡 HIGH - Type Safety Issues (30+ instances)

**Locations:** `fastapi_service.py`, tool files, core modules

**Problem Description:**
Inconsistent type hints break static type checking and IDE autocomplete:
- Missing `Optional[]` for parameters with `None` defaults
- Using `Any` without justification
- Missing return type annotations
- Incorrect union syntax

**Current Anti-Patterns:**
```python
# BAD: Missing Optional
def my_func(param: str = None) -> str:  # mypy error!
    pass

# BAD: Unnecessary Any
def process(data: Any) -> Any:  # What does this do?
    pass

# BAD: Missing return type
def calculate(x, y):  # No type info
    return x + y
```

### Solution

**Type Hint Best Practices:**

```python
from typing import Optional, Union, List, Dict, Any, TypeVar, Generic

# GOOD: Explicit Optional
def my_func(param: Optional[str] = None) -> Optional[str]:
    if param is None:
        return None
    return param.upper()

# GOOD: Specific types instead of Any
def process_data(data: List[Dict[str, Union[str, int]]]) -> List[str]:
    return [str(item) for item in data]

# GOOD: Generic types with TypeVar
T = TypeVar('T')

def first_or_none(items: List[T]) -> Optional[T]:
    return items[0] if items else None

# GOOD: Type: ignore with justification
def dynamic_import(module_name: str) -> Any:  # type: ignore[return]
    # Justification: Dynamic imports can't be typed statically
    return importlib.import_module(module_name)

# GOOD: Protocol for duck typing
from typing import Protocol

class Closeable(Protocol):
    def close(self) -> None: ...

def close_resource(resource: Closeable) -> None:
    resource.close()
```

**mypy Configuration:**
```ini
# mypy.ini
[mypy]
python_version = 3.10
strict = True
warn_return_any = True
warn_unused_configs = True
disallow_untyped_defs = True
disallow_any_generics = True

# Per-module exceptions
[mypy-tests.*]
disallow_untyped_defs = False

[mypy-ipfs_datasets_py.mcp_server.tools.*]
# Tools can be less strict initially
warn_return_any = False
```

### Implementation Plan

**Effort:** 4-6 hours (can be parallelized)

**Steps:**
1. Run `mypy --strict` and collect all errors
2. Fix core modules first (server.py, hierarchical_tool_manager.py)
3. Fix P2P layer (p2p_mcp_registry_adapter.py)
4. Fix sample of tools (10-15 tools)
5. Create type stubs for external dependencies if needed
6. Add mypy to CI pipeline

---

## Issue #5: Closure Variable Capture Bug

### 🔴 CRITICAL - Correctness Bug

**Location:** `p2p_mcp_registry_adapter.py:194-206`

**Problem Description:**
Loop variables captured in closures reference the last value, causing all tool wrappers to use the final category/name values.

**Current Buggy Code:**
```python
for cat in categories:
    for name, func in tools.items():
        def wrapper(*args, **kwargs):
            # BUG: 'cat' and 'name' reference final loop values
            return self._execute_tool(cat, name, func, *args, **kwargs)
        result[cat][name] = wrapper
```

**Demonstration of Bug:**
```python
# Simplified example
functions = []
for i in range(3):
    def f():
        return i  # Captures 'i' from enclosing scope
    functions.append(f)

# All functions return 2 (last value)!
print([f() for f in functions])  # [2, 2, 2] - BUG!
```

### Solution

**Fix 1: Default Arguments (Explicit Binding)**
```python
for cat in categories:
    for name, func in tools.items():
        # Fix: Use default arguments for explicit binding
        def wrapper(*args, cat=cat, name=name, func=func, **kwargs):
            return self._execute_tool(cat, name, func, *args, **kwargs)
        result[cat][name] = wrapper
```

**Fix 2: functools.partial (Preferred)**
```python
from functools import partial

for cat in categories:
    for name, func in tools.items():
        # Better: Use partial for explicit binding
        wrapper = partial(self._execute_tool, cat, name, func)
        wrapper.__name__ = f"{cat}_{name}"
        wrapper.__doc__ = func.__doc__
        result[cat][name] = wrapper
```

**Fix 3: Factory Function (Most Explicit)**
```python
def make_wrapper(self, cat: str, name: str, func: Callable) -> Callable:
    """Factory function creates closure with explicit captures."""
    def wrapper(*args, **kwargs):
        return self._execute_tool(cat, name, func, *args, **kwargs)
    wrapper.__name__ = f"{cat}_{name}"
    wrapper.__doc__ = func.__doc__
    return wrapper

for cat in categories:
    for name, func in tools.items():
        wrapper = make_wrapper(self, cat, name, func)
        result[cat][name] = wrapper
```

### Implementation Plan

**Effort:** 1 hour

**Steps:**
1. Apply `functools.partial` fix
2. Write 3 tests to validate fix
3. Add comment explaining the fix

**Tests:**
```python
def test_closure_capture_fix():
    """Test that wrappers capture correct category/name."""
    adapter = P2PMCPRegistryAdapter()
    tools = adapter._get_hierarchical_tools()
    
    # Execute tools from different categories
    result1 = tools["dataset_tools"]["load"]()
    result2 = tools["ipfs_tools"]["add"]()
    
    # Verify correct category was used
    assert "dataset" in result1["category"]
    assert "ipfs" in result2["category"]

def test_multiple_wrappers_distinct():
    """Test that multiple wrappers are independent."""
    wrappers = []
    for i in range(3):
        wrapper = create_wrapper(category=f"cat{i}", name=f"tool{i}")
        wrappers.append(wrapper)
    
    results = [w() for w in wrappers]
    assert results == ["cat0_tool0", "cat1_tool1", "cat2_tool2"]
```

---

## Issue #6: Missing Docstrings on Public APIs

### 🟡 HIGH - Poor Developer Experience (120+ APIs)

**Locations:** Throughout codebase, especially `tool_registry.py:407-417`

**Problem Description:**
Many public functions, classes, and methods lack comprehensive docstrings, making the codebase difficult to understand and use.

**Standard Format (from docs/_example_docstring_format.md):**

```python
def load_dataset(
    source: str,
    split: Optional[str] = None,
    cache_dir: Optional[str] = None,
    trust_remote_code: bool = False
) -> Dict[str, Any]:
    """
    Load a dataset from HuggingFace Hub or local filesystem.
    
    This function provides a unified interface for loading datasets from various
    sources. It supports both remote datasets (HuggingFace Hub) and local files
    (CSV, JSON, Parquet, etc.). The function handles caching automatically and
    can load specific dataset splits.
    
    Args:
        source: Dataset identifier or local file path.
            For HuggingFace Hub: use format "username/dataset" (e.g., "squad")
            For local files: provide absolute or relative path
        split: Optional dataset split to load. Common values:
            - "train": Training split
            - "test": Test split
            - "validation": Validation split
            If None, loads all available splits.
        cache_dir: Optional directory for caching downloaded datasets.
            If None, uses default HuggingFace cache directory (~/.cache/huggingface)
        trust_remote_code: Whether to trust and execute remote code from dataset
            scripts. Default False for security. Only enable for trusted sources.
    
    Returns:
        Dictionary containing dataset information:
        {
            "splits": Dict[str, Dataset],  # Split name to Dataset object
            "metadata": {
                "source": str,              # Original source identifier
                "num_rows": int,           # Total number of rows across all splits
                "num_splits": int,         # Number of splits loaded
                "features": List[str],     # List of feature/column names
                "size_bytes": int          # Approximate size in bytes
            }
        }
    
    Raises:
        FileNotFoundError: If local file path does not exist
        ValueError: If source format is invalid or dataset not found on Hub
        ImportError: If required dependency (datasets library) is not installed
        RuntimeError: If dataset loading fails due to corruption or format issues
    
    Example:
        >>> # Load HuggingFace dataset
        >>> data = load_dataset("squad", split="train")
        >>> print(f"Loaded {data['metadata']['num_rows']} examples")
        Loaded 87599 examples
        
        >>> # Load local CSV file
        >>> data = load_dataset("./data/my_data.csv")
        >>> print(list(data['splits'].keys()))
        ['train']
        
        >>> # Load with custom cache directory
        >>> data = load_dataset(
        ...     "glue",
        ...     split="validation",
        ...     cache_dir="/tmp/datasets"
        ... )
    
    See Also:
        - save_dataset: Save dataset to various formats
        - list_datasets: List available HuggingFace datasets
        - DatasetInfo: Get detailed dataset information
    
    Notes:
        - Large datasets are streamed by default to save memory
        - Local file format is auto-detected from extension
        - Remote datasets are cached automatically
        - For streaming large datasets, use streaming=True parameter
    """
    # Implementation...
```

### Implementation Plan

**Effort:** 8-12 hours (can be highly parallelized)

**Priority Targets:**
1. Core server APIs (server.py, hierarchical_tool_manager.py) - 2 hours
2. P2P layer APIs (p2p_*.py) - 2 hours
3. Tool registry APIs (tool_registry.py, tool_metadata.py) - 1 hour
4. Sample tools (10-15 tools) - 3 hours
5. Utility functions - 2 hours

**Steps:**
1. Create docstring template checklist
2. Document core APIs first
3. Document high-usage tools
4. Generate API documentation with Sphinx
5. Review generated docs for completeness

---

## Issue #7: Complex Import Error Handling

### 🟢 MEDIUM - Maintenance Burden

**Location:** `server.py:26-102` (75 lines of import error handling)

**Problem Description:**
Complex logic to handle MCP library shadowing by ipfs_kit_py. While functional, it's difficult to understand and maintain.

**Solution:**
Document the issue clearly and consider long-term solutions:
1. Rename ipfs_kit_py's mcp.py module
2. Use namespace packages
3. Virtual environment isolation

---

## Issue #8: Async/Sync Pattern Inconsistency

### 🟢 MEDIUM - Fragile Code

**Location:** `p2p_mcp_registry_adapter.py:313-320`

**Problem Description:**
Ad-hoc detection of async functions using `hasattr(res, "__await__")` is fragile.

**Solution:**
Use `asyncio.iscoroutinefunction()` and proper async patterns.

---

## Issue #9: Missing Input Validation

### 🟡 HIGH - Security Risk

**Location:** `fastapi_service.py:385-410`

**Problem Description:**
No bounds checking on request parameters can lead to DoS.

**Solution:**
Use Pydantic validators with proper limits (covered in detail in main plan).

---

## Issue #10: asyncio.run() in Running Event Loop

### 🔴 CRITICAL - Runtime Error

**Location:** `p2p_mcp_registry_adapter.py:162, 177`

**Problem Description:**
Calling `asyncio.run()` from within a running event loop causes `RuntimeError`.

**Solution:**
Use proper async context or cache results (covered in detail in main plan).

---

## Summary

This document identifies 10 critical architectural issues in the MCP server codebase. The issues range from correctness bugs (closure capture, event loop problems) to maintainability concerns (complex functions, missing docs) to security risks (input validation).

**Priority Order for Fixes:**
1. Issue #5: Closure bug (1 hour) - CRITICAL correctness bug
2. Issue #10: Event loop bug (2-3 hours) - CRITICAL runtime error
3. Issue #1: Complex function (4-6 hours) - HIGH complexity reduction
4. Issue #2: Bare exceptions (3-4 hours) - HIGH reliability improvement
5. Issue #3: Import error handling (2-3 hours) - HIGH user experience
6. Issue #9: Input validation (2-3 hours) - HIGH security
7. Issue #4: Type hints (4-6 hours) - HIGH, can parallelize
8. Issue #6: Docstrings (8-12 hours) - HIGH, can parallelize
9. Issue #8: Async patterns (1-2 hours) - MEDIUM
10. Issue #7: Import complexity (documentation only) - MEDIUM

**Total Effort:** 30-45 hours

**Expected Outcomes:**
- Zero correctness bugs
- Significantly improved maintainability
- Better type safety and IDE support
- Comprehensive documentation
- Improved error handling

---

**Document Status:** COMPLETE  
**Last Updated:** 2026-02-19  
**Next Review:** After Phase 2 Week 6 completion  
**Version:** 1.0
