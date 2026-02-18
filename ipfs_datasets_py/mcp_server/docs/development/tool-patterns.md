# Tool Development Patterns

**Last Updated:** 2026-02-18  
**Status:** Active Standard  
**Audience:** Tool Developers

---

## Overview

This document defines the standard patterns for creating MCP server tools. All new tools MUST follow these patterns. Existing tools SHOULD be migrated to these patterns when modified.

---

## The Golden Rule

> **Tools are thin wrappers. All business logic lives in core modules.**

Tools should be:
- **< 100 lines** (excluding schemas)
- **Async by default** (unless core module is sync)
- **Type-hinted** (all parameters and returns)
- **Well-documented** (comprehensive docstrings)
- **Tested** (unit + integration tests)

---

## Pattern 1: Simple Async Function Tool ⭐ RECOMMENDED

**Use for:** Single-purpose tools with simple parameters

**Example:**

```python
"""
Load Dataset Tool

Loads a dataset from a source and returns the result.
Core Module: ipfs_datasets_py.core_operations.DatasetLoader
"""

from typing import Optional, Dict, Any
from ipfs_datasets_py.mcp_server.tool_wrapper import wrap_function_as_tool
from ipfs_datasets_py.core_operations import DatasetLoader

@wrap_function_as_tool(
    name="load_dataset",
    description="Load a dataset from a source",
    category="dataset_tools",
    tags=["dataset", "loading"]
)
async def load_dataset(
    source: str,
    format: Optional[str] = None,
    **kwargs
) -> Dict[str, Any]:
    """
    Load a dataset from the specified source.
    
    This tool is a thin wrapper around DatasetLoader from core_operations.
    All business logic for dataset loading is in the core module.
    
    Args:
        source: Dataset source identifier (file path, URL, or dataset name)
        format: Optional format specification (json, csv, parquet, etc.)
        **kwargs: Additional options passed to the loader
    
    Returns:
        Dictionary with:
            - status: "success" or "error"
            - data: Loaded dataset (if successful)
            - message: Status message
            - metadata: Dataset metadata
    
    Raises:
        ValueError: If source is invalid
        FileNotFoundError: If source file doesn't exist
    
    Example:
        >>> result = await load_dataset("data.json")
        >>> print(result["status"])
        success
    """
    # 1. Minimal validation (only check required params)
    if not source:
        return {
            "status": "error",
            "message": "source parameter is required"
        }
    
    # 2. Delegate to core module
    loader = DatasetLoader()
    try:
        result = await loader.load(source, format=format, **kwargs)
        return {
            "status": "success",
            "data": result
        }
    except Exception as e:
        return {
            "status": "error",
            "message": str(e)
        }
```

**Characteristics:**
- ✅ Single function with decorator
- ✅ Async execution
- ✅ Type hints on all parameters
- ✅ Comprehensive docstring
- ✅ Delegates to core module
- ✅ Minimal validation
- ✅ Standard error handling

---

## Pattern 2: Multiple Related Tools in One File

**Use for:** Group of related tools in the same category

**Example:**

```python
"""
Search Tools

Semantic, similarity, and faceted search tools.
Core Module: ipfs_datasets_py.search.search_tools_api
"""

from typing import Optional, List, Dict, Any
from ipfs_datasets_py.mcp_server.tool_wrapper import wrap_function_as_tool
from ipfs_datasets_py.search.search_tools_api import (
    semantic_search_from_parameters,
    similarity_search_from_parameters,
    faceted_search_from_parameters
)

@wrap_function_as_tool(
    name="semantic_search",
    description="Perform semantic search using embeddings",
    category="search_tools",
    tags=["search", "semantic", "embeddings"]
)
async def semantic_search(
    query: str,
    model: str = "default",
    top_k: int = 5,
    **kwargs
) -> Dict[str, Any]:
    """Perform semantic search."""
    if not query:
        return {"status": "error", "message": "query is required"}
    
    return await semantic_search_from_parameters(
        query=query,
        model=model,
        top_k=top_k,
        **kwargs
    )


@wrap_function_as_tool(
    name="similarity_search",
    description="Find similar items using cosine similarity",
    category="search_tools",
    tags=["search", "similarity"]
)
async def similarity_search(
    query: str,
    threshold: float = 0.7,
    top_k: int = 5,
    **kwargs
) -> Dict[str, Any]:
    """Find similar items."""
    if not query:
        return {"status": "error", "message": "query is required"}
    
    return await similarity_search_from_parameters(
        query=query,
        threshold=threshold,
        top_k=top_k,
        **kwargs
    )


@wrap_function_as_tool(
    name="faceted_search",
    description="Search with faceted filters",
    category="search_tools",
    tags=["search", "faceted", "filters"]
)
async def faceted_search(
    query: str,
    facets: Optional[List[str]] = None,
    filters: Optional[Dict[str, Any]] = None,
    **kwargs
) -> Dict[str, Any]:
    """Faceted search with filters."""
    if not query:
        return {"status": "error", "message": "query is required"}
    
    return await faceted_search_from_parameters(
        query=query,
        facets=facets or [],
        filters=filters or {},
        **kwargs
    )
```

**Characteristics:**
- ✅ Multiple tools in one file (logically grouped)
- ✅ Each tool is independent
- ✅ Shared imports from same core module
- ✅ Consistent error handling
- ✅ Similar structure across all tools

---

## Pattern 3: Class-Based Tool (LEGACY)

**Use for:** Tools requiring persistent state or complex lifecycle management

⚠️ **WARNING:** Only use this pattern when you MUST maintain state across calls. For most tools, use Pattern 1 or 2.

**Example:**

```python
"""
Stateful Cache Tool

Manages a persistent cache with TTL support.
Core Module: ipfs_datasets_py.core_operations.CacheManager
"""

from typing import Dict, Any, Optional
from ipfs_datasets_py.mcp_server.tool_registry import ClaudeMCPTool
from ipfs_datasets_py.core_operations import CacheManager

class CacheTool(ClaudeMCPTool):
    """
    Tool for managing a persistent cache.
    
    This tool maintains state across calls and should be initialized once
    per session. Use class-based pattern only when state persistence is required.
    """
    
    def __init__(self, cache_manager: Optional[CacheManager] = None):
        super().__init__()
        self.name = "cache_get"
        self.description = "Get a value from the cache"
        self.category = "cache_tools"
        self.tags = ["cache", "storage"]
        
        # State management (why we use class pattern)
        self.cache_manager = cache_manager or CacheManager()
        
        self.input_schema = {
            "type": "object",
            "properties": {
                "key": {
                    "type": "string",
                    "description": "Cache key to retrieve"
                }
            },
            "required": ["key"]
        }
    
    async def execute(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """Execute the cache get operation."""
        key = parameters.get("key")
        
        if not key:
            return {
                "status": "error",
                "message": "key is required"
            }
        
        # Delegate to core module (with persistent state)
        try:
            value = await self.cache_manager.get(key)
            return {
                "status": "success",
                "value": value
            }
        except Exception as e:
            return {
                "status": "error",
                "message": str(e)
            }
```

**Characteristics:**
- ⚠️ Class inheritance from ClaudeMCPTool
- ⚠️ Manual schema definition
- ⚠️ More boilerplate than function pattern
- ✅ Supports persistent state
- ✅ Still delegates to core module

---

## Pattern Selection Guide

### Use Pattern 1 (Simple Function) when:
- ✅ Single-purpose tool
- ✅ Stateless execution
- ✅ Simple parameters
- ✅ No persistent state needed

### Use Pattern 2 (Multiple Functions) when:
- ✅ Related tools in same category
- ✅ Share same core module
- ✅ Logical grouping makes sense

### Use Pattern 3 (Class-Based) when:
- ⚠️ Must maintain state across calls
- ⚠️ Complex lifecycle management
- ⚠️ Resource pooling needed
- ⚠️ Session-based operations

**Default:** Use Pattern 1 unless you have a specific reason not to.

---

## Code Quality Requirements

### 1. Type Hints (REQUIRED)

All parameters and return types MUST have type hints:

```python
async def tool_name(
    param1: str,                    # ✅ Type hint
    param2: Optional[int] = None,   # ✅ Optional type
    **kwargs                        # ✅ OK for catch-all
) -> Dict[str, Any]:                # ✅ Return type
    ...
```

### 2. Docstrings (REQUIRED)

All tools MUST have comprehensive docstrings:

```python
async def tool_name(...):
    """
    Brief one-line description.
    
    Longer description explaining what the tool does,
    which core module it uses, and any important notes.
    
    Args:
        param1: Description of param1
        param2: Description of param2
    
    Returns:
        Dictionary with:
            - status: "success" or "error"
            - result: The actual result
            - message: Optional message
    
    Raises:
        ValueError: When validation fails
        SomeError: When something goes wrong
    
    Example:
        >>> result = await tool_name("input")
        >>> print(result["status"])
        success
    """
```

### 3. Error Handling (REQUIRED)

All tools MUST handle errors gracefully:

```python
# ✅ GOOD: Structured error response
try:
    result = await core_function()
    return {"status": "success", "result": result}
except Exception as e:
    return {"status": "error", "message": str(e)}

# ❌ BAD: Unhandled exceptions
result = await core_function()  # May raise
return result
```

### 4. Parameter Validation (MINIMAL)

Only validate what's absolutely necessary:

```python
# ✅ GOOD: Minimal validation
if not required_param:
    return {"status": "error", "message": "required_param is required"}

# ❌ BAD: Business logic validation (belongs in core module)
if param < 0 or param > 100:
    return {"status": "error", "message": "param must be 0-100"}
```

### 5. Line Count (TARGET < 100)

Keep tools concise:

```python
# ✅ GOOD: 20-50 lines typical
@wrap_function_as_tool(...)
async def simple_tool(param: str) -> dict:
    """Docstring."""
    if not param:
        return {"status": "error", "message": "required"}
    
    service = CoreService()
    result = await service.work(param)
    return {"status": "success", "result": result}

# ❌ BAD: 200+ lines (extract to core module)
```

---

## Anti-Patterns to Avoid

### ❌ Anti-Pattern 1: Business Logic in Tool

```python
# ❌ BAD: Data processing in tool
@wrap_function_as_tool(...)
async def process_data(data: List[dict]) -> dict:
    # Business logic in tool (should be in core module)
    filtered = [d for d in data if d['value'] > 0]
    normalized = [{'val': d['value'] / 100} for d in filtered]
    aggregated = sum(n['val'] for n in normalized)
    return {"result": aggregated}
```

```python
# ✅ GOOD: Delegate to core module
@wrap_function_as_tool(...)
async def process_data(data: List[dict]) -> dict:
    processor = DataProcessor()  # Core module
    result = await processor.process(data)
    return {"result": result}
```

### ❌ Anti-Pattern 2: No Core Module Import

```python
# ❌ BAD: Self-contained tool
@wrap_function_as_tool(...)
async def calculate(a: int, b: int) -> dict:
    result = a + b  # Logic in tool
    return {"result": result}
```

```python
# ✅ GOOD: Uses core module
from ipfs_datasets_py.processors import Calculator

@wrap_function_as_tool(...)
async def calculate(a: int, b: int) -> dict:
    calc = Calculator()
    result = calc.add(a, b)
    return {"result": result}
```

### ❌ Anti-Pattern 3: Complex Validation

```python
# ❌ BAD: Business rules in tool
@wrap_function_as_tool(...)
async def create_user(name: str, age: int) -> dict:
    if len(name) < 3:
        return {"error": "Name too short"}
    if age < 13:
        return {"error": "Must be 13+"}
    if not re.match(r'^[a-zA-Z]+$', name):
        return {"error": "Name must be letters only"}
    # ... more validation
```

```python
# ✅ GOOD: Core module validates
from ipfs_datasets_py.user_management import UserService

@wrap_function_as_tool(...)
async def create_user(name: str, age: int) -> dict:
    service = UserService()
    # Core module handles all validation
    return await service.create_user(name, age)
```

---

## Testing Your Tools

### Unit Test Template

```python
import pytest
from ipfs_datasets_py.mcp_server.tools.your_tool import your_tool_function

@pytest.mark.asyncio
async def test_tool_success():
    """Test successful execution."""
    result = await your_tool_function("valid_input")
    assert result["status"] == "success"
    assert "result" in result

@pytest.mark.asyncio
async def test_tool_validation():
    """Test parameter validation."""
    result = await your_tool_function("")
    assert result["status"] == "error"
    assert "required" in result["message"].lower()

@pytest.mark.asyncio
async def test_tool_error_handling():
    """Test error handling."""
    result = await your_tool_function("invalid_input_that_causes_error")
    assert result["status"] == "error"
    assert "message" in result
```

---

## Checklist for New Tools

- [ ] Uses Pattern 1, 2, or 3 (with justification for Pattern 3)
- [ ] < 100 lines (excluding schemas)
- [ ] Imports from core module (ipfs_datasets_py.*)
- [ ] All parameters have type hints
- [ ] Comprehensive docstring
- [ ] Error handling returns structured response
- [ ] Minimal validation (only required params)
- [ ] Has unit tests
- [ ] Documented in tool category README

---

## Related Documentation

- [Thin Tool Architecture](../../THIN_TOOL_ARCHITECTURE.md) - Overall architecture
- [Tool Template](./tool-template.py) - Copy-paste template
- [Tool Migration Guide](./tool-migration-guide.md) - Migrating legacy tools
- [Testing Guide](./testing.md) - Comprehensive testing guidelines

---

**Last Updated:** 2026-02-18  
**Version:** 1.0  
**Status:** Active Standard
