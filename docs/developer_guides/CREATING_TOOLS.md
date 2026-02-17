# Creating New MCP Tools

Guide for developers to create new MCP tools following the thin wrapper pattern.

## Thin Wrapper Pattern

**ALL MCP tools MUST be thin wrappers** that delegate to core business logic.

### Pattern Template

```python
"""
MCP tool for [functionality].

This is a thin wrapper around core business logic.
"""

async def tool_name(param1: str, param2: Optional[int] = None) -> Dict[str, Any]:
    """
    [Description of what the tool does].
    
    Args:
        param1: [Description]
        param2: [Description]
    
    Returns:
        Dict with status, result, and optional error
    """
    # Import from core module
    from ipfs_datasets_py.core_operations import CoreClass
    
    # Delegate to core logic
    manager = CoreClass()
    result = await manager.method(param1, param2)
    
    return result
```

## Step-by-Step Guide

### Step 1: Create Core Business Logic

First, create the business logic in `ipfs_datasets_py/core_operations/`:

```python
# ipfs_datasets_py/core_operations/my_feature.py

class MyFeatureManager:
    """Core business logic for my feature."""
    
    def __init__(self, config: Optional[Dict] = None):
        self.config = config or {}
    
    async def do_something(self, input_data: str) -> Dict[str, Any]:
        """
        Core logic implementation.
        
        This is where ALL business logic lives.
        """
        try:
            # Validation
            if not input_data:
                return {"status": "error", "error": "Input required"}
            
            # Processing
            result = process(input_data)
            
            # Return
            return {
                "status": "success",
                "result": result,
                "input": input_data
            }
        except Exception as e:
            return {
                "status": "error",
                "error": str(e)
            }
```

### Step 2: Export from core_operations

Add to `ipfs_datasets_py/core_operations/__init__.py`:

```python
from .my_feature import MyFeatureManager

__all__ = [
    'DatasetLoader',
    'IPFSPinner',
    'KnowledgeGraphManager',
    'MyFeatureManager',  # Add new class
]
```

### Step 3: Create MCP Tool (Thin Wrapper)

Create tool in `ipfs_datasets_py/mcp_server/tools/my_category/`:

```python
# ipfs_datasets_py/mcp_server/tools/my_category/my_tool.py

"""
MCP tool for [feature].

Thin wrapper around MyFeatureManager.
"""

from typing import Dict, Any, Optional


async def my_tool(
    input_data: str,
    options: Optional[Dict] = None
) -> Dict[str, Any]:
    """
    [Tool description].
    
    Args:
        input_data: Input data to process
        options: Optional configuration
    
    Returns:
        Dict with status and result
    
    Example:
        >>> result = await my_tool("data")
        >>> print(result["status"])
        "success"
    """
    from ipfs_datasets_py.core_operations import MyFeatureManager
    
    manager = MyFeatureManager(config=options)
    return await manager.do_something(input_data)
```

### Step 4: Register Tool

Add to category's `__init__.py`:

```python
# ipfs_datasets_py/mcp_server/tools/my_category/__init__.py

from .my_tool import my_tool

__all__ = ['my_tool']
```

### Step 5: Add Tests

Create tests in `tests/unit/core_operations/`:

```python
# tests/unit/core_operations/test_my_feature.py

import pytest
from ipfs_datasets_py.core_operations import MyFeatureManager


@pytest.mark.asyncio
async def test_my_feature_success():
    """Test successful feature operation."""
    # GIVEN - Manager and input
    manager = MyFeatureManager()
    input_data = "test data"
    
    # WHEN - Processing
    result = await manager.do_something(input_data)
    
    # THEN - Success
    assert result["status"] == "success"
    assert "result" in result
```

### Step 6: Add CLI Command (Optional)

Add to `ipfs_datasets_cli.py`:

```python
# In execute_heavy_command() function

elif command == 'my-feature':
    from ipfs_datasets_py.core_operations import MyFeatureManager
    
    manager = MyFeatureManager()
    result = anyio.run(manager.do_something, input_data)
    print(json.dumps(result, indent=2))
```

## Benefits of This Pattern

### 1. Code Reusability
```python
# MCP Tool
await my_tool("data")

# CLI
ipfs-datasets my-feature "data"

# Python Import
from ipfs_datasets_py.core_operations import MyFeatureManager
manager = MyFeatureManager()
await manager.do_something("data")
```

All three use the SAME business logic!

### 2. Easy Testing
Test core logic independently of MCP/CLI layers.

### 3. Maintainability
Change logic once, propagates everywhere.

### 4. Documentation
Core modules have comprehensive API docs.

## Common Mistakes to Avoid

### ❌ DON'T: Put business logic in MCP tool

```python
# BAD - Business logic in MCP tool
async def bad_tool(input_data):
    # 200 lines of business logic here
    result = complex_processing(input_data)
    return result
```

### ✅ DO: Thin wrapper with delegation

```python
# GOOD - Thin wrapper
async def good_tool(input_data):
    from ipfs_datasets_py.core_operations import Manager
    return await Manager().process(input_data)
```

### ❌ DON'T: Duplicate logic across tools

```python
# BAD - Logic duplicated in multiple tools
async def tool1(data):
    # Same logic
    pass

async def tool2(data):
    # Same logic duplicated
    pass
```

### ✅ DO: Share logic via core module

```python
# GOOD - Shared logic
async def tool1(data):
    from ipfs_datasets_py.core_operations import Manager
    return await Manager().process(data)

async def tool2(data):
    from ipfs_datasets_py.core_operations import Manager
    return await Manager().process(data)
```

## See Also

- [Core Operations API](../api/CORE_OPERATIONS_API.md)
- [Testing Guidelines](TESTING_GUIDELINES.md)
- [Architecture](../../MCP_ARCHITECTURE_DIAGRAM.md)
