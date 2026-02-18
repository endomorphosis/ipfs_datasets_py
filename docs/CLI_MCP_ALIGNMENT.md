# CLI-MCP Alignment Strategy

## Overview

This document defines the alignment strategy between CLI commands and MCP tools to ensure consistent user experience and shared core business logic.

## Current Architecture

Both CLI and MCP tools use the same underlying pattern:

```
CLI Commands                 MCP Tools
     │                           │
     └────> Core Modules <───────┘
            (processors/,
             caching/,
             logic/)
```

## Alignment Principles

### 1. Shared Core Logic

**Status**: ✅ Implemented

Both CLI and MCP delegate to the same core modules:
- Relationship analysis → `processors.relationships`
- Caching → `caching.CacheManager`
- Logic/reasoning → `logic.*`

### 2. Consistent Naming

**Command Structure:**
```
CLI:  ipfs-datasets <category> <action> [options]
MCP:  <category>_tools.<action>() 

Example:
CLI:  ipfs-datasets cache get --key mykey
MCP:  cache_tools.cache_get(key="mykey")
```

### 3. Parameter Compatibility

Parameters should use the same names across CLI and MCP:

```python
# CLI
ipfs-datasets cache set --key KEY --value VALUE --ttl 3600

# MCP
cache_tools.cache_set(key=KEY, value=VALUE, ttl=3600)

# Core Module
CacheManager().set(key=KEY, value=VALUE, ttl=3600)
```

## Command Mapping

### Cache Commands

| CLI Command | MCP Tool | Core Module |
|------------|----------|-------------|
| `cache get KEY` | `cache_tools.cache_get(key)` | `CacheManager.get(key)` |
| `cache set KEY VALUE` | `cache_tools.cache_set(key, value)` | `CacheManager.set(key, value)` |
| `cache delete KEY` | `cache_tools.cache_delete(key)` | `CacheManager.delete(key)` |
| `cache clear [NS]` | `cache_tools.cache_clear(namespace)` | `CacheManager.clear(namespace)` |
| `cache stats` | `cache_tools.cache_stats()` | `CacheManager.get_stats()` |
| `cache optimize` | `cache_tools.optimize_cache()` | `CacheManager.optimize()` |

### Relationship Analysis Commands

| CLI Command | MCP Tool | Core Module |
|------------|----------|-------------|
| `relationships map CORPUS` | `relationship_timeline_tools.map_relationships()` | `EntityExtractor + GraphAnalyzer` |
| `relationships timeline ENTITY` | `relationship_timeline_tools.analyze_entity_timeline()` | `TimelineGenerator` |
| `relationships patterns` | `relationship_timeline_tools.detect_patterns()` | `PatternDetector` |
| `relationships provenance ENTITY` | `relationship_timeline_tools.track_provenance()` | `ProvenanceTracker` |

## Parameter Naming Standards

### Standard Parameters

- `key` - Cache key or identifier
- `value` - Data value
- `ttl` - Time to live (seconds)
- `namespace` - Logical grouping
- `corpus_data` - Document corpus (JSON string or dict)
- `entity_id` - Entity identifier
- `confidence_threshold` - Minimum confidence (0.0-1.0)
- `max_depth` - Maximum traversal depth
- `time_granularity` - Time bucket size (hour, day, week, month)

### Consistency Rules

1. Use snake_case for all parameters
2. Boolean flags should be `include_*` or `enable_*`
3. Thresholds should be `min_*` or `max_*`
4. Time periods should be `*_seconds`, `*_hours`, or `*_days`

## Implementation Status

### Phase 2C: Core Module Extraction ✅

- [x] Relationship tools use `processors.relationships`
- [x] Cache tools use `caching.CacheManager`
- [x] Deontic tools use `logic.deontic.analyzer`

### Phase 4: CLI Integration ⚠️ Partial

Current CLI status:
- CLI dynamically discovers MCP tools
- CLI delegates to MCP tools
- **Gap**: CLI doesn't directly use core modules (goes through MCP layer)

**Recommendation**: Update CLI to optionally bypass MCP and call core modules directly for better performance.

## Future Enhancements

### 1. Direct Core Module Access in CLI

Allow CLI to use core modules directly:

```python
# Current (2 hops)
CLI → MCP Tool → Core Module

# Proposed (1 hop)
CLI → Core Module
```

**Benefits**:
- Faster execution (no MCP overhead)
- Simpler stack traces
- Easier debugging

**Implementation**:
```python
# cli_direct.py
from ipfs_datasets_py.caching import CacheManager

def cache_command(action, **kwargs):
    manager = CacheManager()
    if action == "get":
        return manager.get(**kwargs)
    elif action == "set":
        return manager.set(**kwargs)
    # ...
```

### 2. Unified Configuration

Share configuration between CLI and MCP:

```yaml
# config.yaml
cache:
  default_ttl: 3600
  max_size_mb: 1000
  optimization_strategy: lru

relationships:
  confidence_threshold: 0.7
  max_depth: 5
```

### 3. Consistent Error Handling

Standardize error responses:

```python
{
    "success": false,
    "error": "Error message",
    "error_code": "CACHE_KEY_NOT_FOUND",
    "timestamp": "2024-01-01T00:00:00"
}
```

## Testing

### Equivalence Tests

Verify CLI and MCP produce identical results:

```python
def test_cache_equivalence():
    # Via CLI
    cli_result = subprocess.run([
        "ipfs-datasets", "cache", "get", "--key", "test"
    ], capture_output=True)
    
    # Via MCP
    mcp_result = await cache_tools.cache_get(key="test")
    
    # Should be identical
    assert cli_result == mcp_result
```

## References

- Core Modules API: `docs/CORE_MODULES_API.md`
- MCP Testing Guide: `docs/MCP_TESTING_GUIDE.md`
- Third-Party Integration: `docs/THIRD_PARTY_INTEGRATION.md`
