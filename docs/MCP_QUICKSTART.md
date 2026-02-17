# Quick Start: MCP Hierarchical Tool Manager

**For developers working on MCP tools**

## Overview

The hierarchical tool manager reduces context window usage from 347 tools to 4 meta-tools by organizing tools into categories and loading them dynamically on demand.

## For Tool Users (LLM Assistants)

### 1. Discover Available Categories
```python
result = await tools_list_categories(include_count=True)
# Returns: {"status": "success", "categories": [...]}
```

### 2. List Tools in a Category
```python
result = await tools_list_tools("dataset_tools")
# Returns: {"status": "success", "tools": [...]}
```

### 3. Get Tool Schema (Optional)
```python
result = await tools_get_schema("dataset_tools", "load_dataset")
# Returns: {"status": "success", "schema": {...}}
```

### 4. Execute a Tool
```python
result = await tools_dispatch(
    category="dataset_tools",
    tool="load_dataset",
    params={"source": "squad", "format": "json"}
)
# Returns: Tool execution result
```

## For Tool Developers

### Creating a New Tool (After Phase 2)

#### Step 1: Create Core Business Logic
```python
# ipfs_datasets_py/your_module/your_logic.py
"""Core business logic for your feature."""

class YourFeature:
    """Business logic class."""
    
    async def execute(self, param1: str, param2: int = 10):
        """Execute the core operation.
        
        Args:
            param1: Description
            param2: Description (default: 10)
        
        Returns:
            Dict with results
        """
        # All business logic goes here
        result = self._do_something(param1, param2)
        return {
            "status": "success",
            "result": result
        }
```

#### Step 2: Create MCP Tool Wrapper
```python
# ipfs_datasets_py/mcp_server/tools/your_category/your_tool.py
"""MCP wrapper for your feature.

Core implementation: ipfs_datasets_py.your_module.your_logic.YourFeature
"""

async def your_tool(param1: str, param2: int = 10):
    """Execute your feature.
    
    Args:
        param1: Description
        param2: Description (default: 10)
    
    Returns:
        Dict with execution results
    """
    from ipfs_datasets_py.your_module.your_logic import YourFeature
    
    try:
        feature = YourFeature()
        return await feature.execute(param1, param2)
    except Exception as e:
        return {
            "status": "error",
            "error": str(e)
        }
```

#### Step 3: Export from Category __init__.py
```python
# ipfs_datasets_py/mcp_server/tools/your_category/__init__.py
"""Your category tools."""

from .your_tool import your_tool

__all__ = ["your_tool"]
```

That's it! The hierarchical tool manager will automatically discover and register your tool.

### Tool Development Rules

**DO:**
- ✅ Keep business logic in `ipfs_datasets_py/` core modules
- ✅ Make MCP tools thin wrappers (5-20 lines)
- ✅ Handle errors gracefully
- ✅ Return consistent dict format: `{"status": "success|error", ...}`
- ✅ Add comprehensive docstrings
- ✅ Add tests for core module

**DON'T:**
- ❌ Put business logic in MCP tool files
- ❌ Import from other MCP tools
- ❌ Use synchronous blocking operations
- ❌ Forget error handling
- ❌ Return non-dict values

## Testing Your Tool

### Test Core Logic Directly
```python
# tests/unit/your_module/test_your_logic.py
import pytest
from ipfs_datasets_py.your_module.your_logic import YourFeature

@pytest.mark.anyio
async def test_your_feature():
    """Test the core business logic."""
    feature = YourFeature()
    result = await feature.execute("test_param", 5)
    
    assert result["status"] == "success"
    assert "result" in result
```

### Test MCP Tool Wrapper
```python
# tests/unit/mcp_server/test_your_tool.py
import pytest
from ipfs_datasets_py.mcp_server.hierarchical_tool_manager import tools_dispatch

@pytest.mark.anyio
async def test_dispatch_your_tool():
    """Test tool via hierarchical manager."""
    result = await tools_dispatch(
        category="your_category",
        tool="your_tool",
        params={"param1": "test", "param2": 5}
    )
    
    assert result["status"] == "success"
```

### Test with Demo Script
```bash
# List tools in your category
python3 scripts/demo/demo_hierarchical_tools.py --list-tools your_category

# Get tool schema
python3 scripts/demo/demo_hierarchical_tools.py --get-schema your_category your_tool

# Run your tool
python3 scripts/demo/demo_hierarchical_tools.py --run your_category your_tool \
    --params '{"param1": "test", "param2": 5}'
```

## Common Patterns

### Pattern 1: Simple Synchronous Tool
```python
async def simple_tool(input: str):
    """Simple tool that doesn't need async."""
    from ipfs_datasets_py.module import process_sync
    
    result = process_sync(input)  # Sync operation
    return {"status": "success", "result": result}
```

### Pattern 2: Async I/O Tool
```python
async def async_tool(url: str):
    """Tool with async I/O operations."""
    from ipfs_datasets_py.module import AsyncProcessor
    
    processor = AsyncProcessor()
    result = await processor.fetch(url)  # Async operation
    return {"status": "success", "result": result}
```

### Pattern 3: Tool with Multiple Operations
```python
async def complex_tool(input: str, operation: str = "process"):
    """Tool supporting multiple operations."""
    from ipfs_datasets_py.module import ComplexProcessor
    
    processor = ComplexProcessor()
    
    if operation == "process":
        result = await processor.process(input)
    elif operation == "analyze":
        result = await processor.analyze(input)
    else:
        return {"status": "error", "error": f"Unknown operation: {operation}"}
    
    return {"status": "success", "result": result}
```

### Pattern 4: Tool with Error Handling
```python
async def robust_tool(input: str):
    """Tool with comprehensive error handling."""
    from ipfs_datasets_py.module import Processor
    import logging
    
    logger = logging.getLogger(__name__)
    
    try:
        processor = Processor()
        result = await processor.execute(input)
        return {"status": "success", "result": result}
        
    except ValueError as e:
        logger.warning(f"Validation error: {e}")
        return {"status": "error", "error": f"Invalid input: {e}"}
        
    except Exception as e:
        logger.error(f"Unexpected error: {e}", exc_info=True)
        return {"status": "error", "error": f"Processing failed: {e}"}
```

## Integrating with MCP Server (Phase 4)

When Phase 4 is complete, tools will be automatically available via MCP server:

### server.py Integration
```python
from .hierarchical_tool_manager import (
    tools_list_categories,
    tools_list_tools,
    tools_get_schema,
    tools_dispatch
)

# Register only 4 meta-tools
mcp.add_tool(tools_list_categories, name="tools_list_categories")
mcp.add_tool(tools_list_tools, name="tools_list_tools")
mcp.add_tool(tools_get_schema, name="tools_get_schema")
mcp.add_tool(tools_dispatch, name="tools_dispatch")
```

### Client Usage
```python
# List categories
categories = await mcp.call_tool("tools_list_categories")

# Execute a tool
result = await mcp.call_tool("tools_dispatch", {
    "category": "dataset_tools",
    "tool": "load_dataset",
    "params": {"source": "squad"}
})
```

## CLI Integration (Phase 6)

CLI will use the same core modules:

```python
# ipfs_datasets_cli.py
from ipfs_datasets_py.your_module.your_logic import YourFeature

async def your_command(param1: str, param2: int = 10):
    """CLI command using same core logic."""
    feature = YourFeature()
    return await feature.execute(param1, param2)
```

## Migration Checklist

When migrating existing tools:

- [ ] Identify business logic in tool file
- [ ] Create core module in `ipfs_datasets_py/`
- [ ] Extract business logic to core module
- [ ] Convert tool to thin wrapper
- [ ] Update imports
- [ ] Add/update tests for core module
- [ ] Add/update tests for MCP wrapper
- [ ] Test via demo script
- [ ] Update CLI to use core module (if applicable)
- [ ] Update documentation
- [ ] Mark old tool as deprecated (if needed)

## Resources

- **Refactoring Plan:** `docs/MCP_REFACTORING_PLAN.md`
- **Architecture Diagram:** `docs/MCP_ARCHITECTURE_DIAGRAM.md`
- **Implementation Summary:** `docs/MCP_REFACTORING_SUMMARY.md`
- **Core Implementation:** `ipfs_datasets_py/mcp_server/hierarchical_tool_manager.py`
- **Demo Script:** `scripts/demo/demo_hierarchical_tools.py`
- **Test Suite:** `tests/unit/mcp_server/test_hierarchical_tool_manager.py`

## Getting Help

1. Review the comprehensive refactoring plan
2. Look at existing well-structured tools (e.g., `graph_tools`)
3. Run the demo script to understand the workflow
4. Check test examples for patterns
5. Ask questions in PR comments or issues

## Current Status (2026-02-17)

- ✅ **Phase 1:** Infrastructure complete
- 🔄 **Phase 2:** Core modules in progress (next step)
- ⏳ **Phase 3-8:** Pending

**You are here:** Creating core business logic modules and converting existing tools to thin wrappers.

---

**Happy Tool Development!** 🛠️

Remember: Business logic in core modules, MCP tools as thin wrappers! ✨
