# Migration Guide: Flat to Hierarchical Tools

Guide for migrating from flat tool registration to hierarchical tool manager.

## Overview

The MCP server refactoring introduces a hierarchical tool manager that reduces context window usage by 99% (from 347 tools to 4 meta-tools).

## Key Changes

### Before (Flat Registration)
```python
# Old way - 347 tools registered at top level
server.register_tool("load_dataset")
server.register_tool("pin_to_ipfs")
server.register_tool("query_knowledge_graph")
# ... 344 more registrations
```

### After (Hierarchical)
```python
# New way - 4 meta-tools for 51 categories
server.register_tool("tools_list_categories")
server.register_tool("tools_list_tools")
server.register_tool("tools_get_schema")
server.register_tool("tools_dispatch")
```

## Usage Changes

### Discovering Tools

**Before:**
```python
# Had to know tool names in advance
# All 347 tools loaded upfront
```

**After:**
```python
from ipfs_datasets_py.mcp_server.hierarchical_tool_manager import HierarchicalToolManager

manager = HierarchicalToolManager()

# Discover categories
categories = manager.list_categories()
# Returns: ['dataset_tools', 'graph_tools', 'ipfs_tools', ...]

# Discover tools in category
tools = manager.list_tools('graph_tools')
# Returns: ['graph_create', 'graph_add_entity', ...]
```

### Executing Tools

**Before:**
```python
# Direct tool call
result = await load_dataset(source="squad")
```

**After:**
```python
# Dispatch through hierarchical manager
result = await manager.dispatch_tool(
    category='dataset_tools',
    tool_name='load_dataset',
    params={'source': 'squad'}
)
```

## Benefits of Migration

### 1. Context Window Savings
- **Before:** ~50-100KB in context (all tools)
- **After:** ~2KB in context (4 meta-tools)
- **Savings:** 96-98% reduction

### 2. Lazy Loading
- **Before:** All tools loaded upfront
- **After:** Tools loaded on-demand
- **Benefit:** Faster startup, lower memory

### 3. Better Organization
- **Before:** Flat list of 347 tools
- **After:** 51 logical categories
- **Benefit:** Easier discovery

### 4. Scalability
- **Before:** Adding tools increases context
- **After:** Adding tools doesn't affect context
- **Benefit:** Can scale to 1000+ tools

## Backward Compatibility

**Both old and new patterns work during migration!**

```python
# Old pattern still works
result = await load_dataset("squad")

# New pattern also works
result = await manager.dispatch_tool('dataset_tools', 'load_dataset', {'source': 'squad'})
```

## Migration Steps

### Step 1: Update Imports

```python
# Add hierarchical manager import
from ipfs_datasets_py.mcp_server.hierarchical_tool_manager import HierarchicalToolManager
```

### Step 2: Create Manager Instance

```python
manager = HierarchicalToolManager()
```

### Step 3: Update Tool Discovery

```python
# Old
# (manual tool listing)

# New
categories = manager.list_categories()
for category in categories:
    tools = manager.list_tools(category)
    print(f"{category}: {tools}")
```

### Step 4: Update Tool Calls

```python
# Old
result = await my_tool(param1, param2)

# New
result = await manager.dispatch_tool(
    'my_category',
    'my_tool',
    {'param1': value1, 'param2': value2}
)
```

### Step 5: Test Thoroughly

```bash
# Run tests
pytest tests/integration/test_mcp_tools_integration.py
pytest tests/compatibility/test_backward_compatibility.py
```

## Common Issues

### Issue 1: Tool Not Found

**Error:**
```
ToolNotFoundError: Tool 'my_tool' not found in category 'my_category'
```

**Solution:**
Verify the tool exists:
```python
tools = manager.list_tools('my_category')
print(tools)
```

### Issue 2: Import Errors

**Error:**
```
ImportError: cannot import name 'HierarchicalToolManager'
```

**Solution:**
Update installation:
```bash
pip install -e ".[all]"
```

### Issue 3: Parameter Format

**Error:**
```
TypeError: dispatch_tool() expects dict for params
```

**Solution:**
```python
# Wrong
result = await manager.dispatch_tool('cat', 'tool', 'value')

# Correct
result = await manager.dispatch_tool('cat', 'tool', {'param': 'value'})
```

## Timeline

- **Week 1-4:** Both patterns supported
- **Week 5-8:** Deprecation warnings added
- **Week 9+:** Old pattern removed

## See Also

- [Architecture Diagram](../../MCP_ARCHITECTURE_DIAGRAM.md)
- [Developer Guide](../developer_guides/CREATING_TOOLS.md)
- [API Reference](../api/CORE_OPERATIONS_API.md)
