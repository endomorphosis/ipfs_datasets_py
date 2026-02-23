# Compatibility Layer Module

**Purpose:** Ensure 100% backward compatibility when migrating from FastAPI-only to dual-runtime architecture.

## Components

### 1. shim.py
**Compatibility shim for wrapping existing tools**
- `CompatibilityShim`: Wraps tools to work with both runtimes
- `ToolCompatibilityChecker`: Validates tool compatibility

### 2. detection.py
**Runtime detection utilities**
- `RuntimeDetector`: Auto-detects appropriate runtime for tools
- `RuntimeValidator`: Validates runtime configuration

### 3. config_migration.py
**Configuration migration helpers**
- `ConfigMigrator`: Migrates old config to new format
- `ConfigValidator`: Validates configuration

### 4. version.py
**API versioning management**
- `APIVersionManager`: Manages API versions
- `DeprecationWarning`: Handles deprecations

## Usage Examples

### Wrapping Existing Tools
```python
from ipfs_datasets_py.mcp_server.compat import CompatibilityShim

shim = CompatibilityShim()

@shim.wrap_tool
async def my_existing_tool(param: str) -> dict:
    return {"result": param}

# Tool now works with both runtimes
result = await my_existing_tool("test")
```

### Runtime Detection
```python
from ipfs_datasets_py.mcp_server.compat import RuntimeDetector

detector = RuntimeDetector()
runtime = detector.detect_runtime(my_tool)
print(f"Tool should use: {runtime}")
```

### Config Migration
```python
from ipfs_datasets_py.mcp_server.compat import ConfigMigrator

migrator = ConfigMigrator()
new_config = migrator.migrate_config(old_config)
```

## Design Principles

1. **Zero Breaking Changes:** All existing tools work without modification
2. **Opt-in Enhancement:** Trio runtime is optional
3. **Graceful Fallback:** Falls back to FastAPI if Trio unavailable
4. **Clear Migration Path:** Step-by-step migration guide

## Testing

Run compatibility tests:
```bash
pytest tests/compat/
```

## Status

- ✅ Module structure defined
- ✅ Core interfaces designed
- ✅ Implementation complete (Phase 2 ✅)
- ✅ Full testing complete (Phase 3/5 ✅)
