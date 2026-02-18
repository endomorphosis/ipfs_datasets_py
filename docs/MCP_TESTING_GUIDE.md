# MCP Testing Guide

## Overview

This guide provides guidelines for testing MCP server tools and ensuring they follow the thin wrapper pattern.

## Testing Infrastructure

### Validators

#### 1. Tool Thinness Validator

Validates that MCP tools are thin wrappers (<400 lines) with minimal complexity.

```bash
# Run validator
python scripts/validators/tool_thinness_validator.py

# With custom thresholds
python scripts/validators/tool_thinness_validator.py --max-lines 350 --max-complexity 8

# Generate JSON report
python scripts/validators/tool_thinness_validator.py --report json --output thinness_report.json
```

**Checks:**
- Line count (target: <400 lines)
- Cyclomatic complexity (target: <10 per function)
- Imports from core modules

**Success Criteria:**
- ✓ Tool has <400 lines of code
- ✓ Functions have complexity <10
- ✓ Imports from `ipfs_datasets_py.processors`, `ipfs_datasets_py.caching`, or `ipfs_datasets_py.logic`

#### 2. Core Import Checker

Validates that MCP tools properly import and delegate to core modules.

```bash
# Run checker
python scripts/validators/core_import_checker.py

# Generate JSON report
python scripts/validators/core_import_checker.py --report json --output import_report.json
```

**Checks:**
- Core module imports
- Delegation patterns
- Business logic detection

**Delegation Patterns:**
- **good**: >70% of functions delegate to core modules
- **partial**: 30-70% delegation
- **poor**: <30% delegation
- **none**: No core module imports

## Thin Wrapper Pattern

### Architecture

```
┌─────────────────┐
│   MCP Tool      │  ← Thin wrapper (~100-400 lines)
│  (thin wrapper) │
└────────┬────────┘
         │ imports & delegates
         ↓
┌─────────────────┐
│  Core Module    │  ← Business logic (reusable)
│ (processors/    │
│  caching/logic/)│
└─────────────────┘
```

### Example: Refactored Cache Tools

**Before (thick tool - 709 lines):**
```python
# All business logic embedded in MCP tool
async def manage_cache(operation, key, value, ...):
    # 100+ lines of cache logic here
    if operation == "get":
        # ... complex logic
    elif operation == "set":
        # ... complex logic
    # etc.
```

**After (thin wrapper - 120 lines + core module 477 lines):**

**MCP Tool (thin wrapper):**
```python
from ipfs_datasets_py.caching import CacheManager

_cache_manager = None

def get_cache_manager() -> CacheManager:
    global _cache_manager
    if _cache_manager is None:
        _cache_manager = CacheManager()
    return _cache_manager

async def manage_cache(operation, key, value, ...):
    manager = get_cache_manager()
    
    if operation == "get":
        return manager.get(key, namespace)
    elif operation == "set":
        return manager.set(key, value, ttl, namespace)
    # Minimal delegation logic only
```

**Core Module (reusable):**
```python
class CacheManager:
    def __init__(self):
        self.storage = {}
        self.metadata = {}
    
    def get(self, key, namespace):
        # Business logic here
        pass
    
    def set(self, key, value, ttl, namespace):
        # Business logic here
        pass
```

### Benefits

1. **Reusability**: Core modules can be used by CLI, MCP, API, and third parties
2. **Testability**: Core modules can be unit tested independently
3. **Maintainability**: Business logic centralized in one place
4. **Context Window**: Thin MCP tools use less tokens

## Testing Guidelines

### Unit Tests for Core Modules

Core modules should have comprehensive unit tests:

```python
# tests/test_cache_manager.py
from ipfs_datasets_py.caching import CacheManager

def test_cache_set_get():
    manager = CacheManager()
    manager.set("key", "value", ttl=3600, namespace="test")
    result = manager.get("key", namespace="test")
    assert result["hit"] is True
    assert result["value"] == "value"

def test_cache_expiration():
    manager = CacheManager()
    manager.set("key", "value", ttl=0, namespace="test")
    # Sleep or manipulate time
    result = manager.get("key", namespace="test")
    assert result["hit"] is False
```

### Integration Tests for MCP Tools

MCP tools should have integration tests that verify delegation:

```python
# tests/mcp/test_cache_tools.py
import asyncio
from ipfs_datasets_py.mcp_server.tools.cache_tools import cache_tools

async def test_cache_set_via_mcp():
    result = await cache_tools.cache_set("key", "value", ttl=3600)
    assert result["success"] is True
    assert result["stored"] is True

async def test_cache_get_via_mcp():
    await cache_tools.cache_set("key", "value")
    result = await cache_tools.cache_get("key")
    assert result["hit"] is True
    assert result["value"] == "value"
```

### Performance Tests

Ensure refactoring doesn't introduce performance regression:

```python
# tests/performance/test_refactored_tools_performance.py
import time
from ipfs_datasets_py.caching import CacheManager

def test_cache_performance():
    manager = CacheManager()
    
    start = time.time()
    for i in range(1000):
        manager.set(f"key_{i}", f"value_{i}")
    set_time = time.time() - start
    
    start = time.time()
    for i in range(1000):
        manager.get(f"key_{i}")
    get_time = time.time() - start
    
    assert set_time < 1.0  # Should complete in < 1 second
    assert get_time < 0.5  # Gets should be faster
```

## Refactoring Workflow

When refactoring a thick MCP tool:

1. **Analyze**: Identify business logic vs MCP glue code
2. **Extract**: Move business logic to core module in appropriate package
   - Relationship/graph logic → `processors/relationships/`
   - Caching logic → `caching/`
   - Logic/reasoning → `logic/`
3. **Create Core Module**: Well-documented, reusable class/functions
4. **Create Thin Wrapper**: Import and delegate to core module
5. **Update Exports**: Add to core module's `__init__.py`
6. **Test**: Unit tests for core, integration tests for MCP tool
7. **Validate**: Run validators to confirm compliance

## Validation Checklist

Before considering refactoring complete:

- [ ] Tool passes thinness validator (<400 lines)
- [ ] Tool passes core import checker (uses core modules)
- [ ] Core module has unit tests (>80% coverage)
- [ ] MCP tool has integration tests
- [ ] Performance tests show no regression
- [ ] Documentation updated (API docs, examples)
- [ ] Third-party usage example created

## Continuous Integration

Add validators to CI pipeline:

```yaml
# .github/workflows/mcp-validation.yml
- name: Validate Tool Thinness
  run: python scripts/validators/tool_thinness_validator.py

- name: Check Core Imports
  run: python scripts/validators/core_import_checker.py
```

## References

- Phase 2C Refactoring Examples:
  - Relationship Timeline Tools: 971→343 lines (65% reduction)
  - Cache Tools: 709→120 lines (83% reduction)
  - Deontological Tools: 594→255 lines (57% reduction)

- Core Modules:
  - `ipfs_datasets_py/processors/relationships/` - 5 modules, 1,312 lines
  - `ipfs_datasets_py/caching/cache_manager.py` - 477 lines
  - `ipfs_datasets_py/logic/deontic/analyzer.py` - 503 lines
