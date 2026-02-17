# P2P Migration Guide - MCP++ Integration

**Date:** 2026-02-17  
**Version:** Phase 1 Complete  
**Status:** Foundation Ready  

This guide helps you migrate to the enhanced P2P capabilities with MCP++ integration in the IPFS Datasets MCP server.

## Overview

Phase 1 of the MCP++ integration project is complete, providing the foundation for advanced P2P capabilities:

- **Import Layer**: Graceful MCP++ imports with availability detection
- **Enhanced Service Manager**: Workflow scheduler, peer registry, and bootstrap integration
- **Enhanced Registry Adapter**: Runtime detection and tool filtering
- **Comprehensive Testing**: 62 tests covering all components

## What's New in Phase 1

### 1. MCP++ Import Layer

New import modules in `ipfs_datasets_py/mcp_server/mcplusplus/`:

- **`__init__.py`**: Capability detection and graceful imports
- **`workflow_scheduler.py`**: P2P workflow scheduler wrapper
- **`task_queue.py`**: P2P task queue wrapper
- **`peer_registry.py`**: Peer discovery and management
- **`bootstrap.py`**: Network bootstrap utilities

### 2. Enhanced P2P Service Manager

The `P2PServiceManager` class now supports:

**New Configuration Options:**
```python
P2PServiceManager(
    enabled=True,
    # Existing options
    queue_path="/tmp/p2p_queue",
    listen_port=4001,
    enable_tools=True,
    enable_cache=True,
    # NEW MCP++ options
    enable_workflow_scheduler=True,  # Enable P2P workflow scheduler
    enable_peer_registry=True,       # Enable peer discovery
    enable_bootstrap=True,            # Enable bootstrap
    bootstrap_nodes=[...],            # Custom bootstrap nodes
)
```

**New Methods:**
- `get_workflow_scheduler()` - Access workflow scheduler instance
- `get_peer_registry()` - Access peer registry instance
- `has_advanced_features()` - Check if MCP++ features available
- `get_capabilities()` - Get detailed capability dict

### 3. Enhanced Registry Adapter

The `P2PMCPRegistryAdapter` class now includes:

**Runtime Detection:**
- Automatic detection of tool runtime (FastAPI vs Trio)
- Runtime metadata on all tool descriptors
- Support for explicit `_mcp_runtime` markers

**Tool Filtering:**
```python
adapter = P2PMCPRegistryAdapter(server)

# Get tools by runtime
trio_tools = adapter.get_trio_tools()
fastapi_tools = adapter.get_fastapi_tools()
all_tools = adapter.get_tools_by_runtime(runtime)

# Runtime statistics
stats = adapter.get_runtime_stats()
print(f"Trio tools: {stats['trio_tools']}")
print(f"FastAPI tools: {stats['fastapi_tools']}")
```

**Tool Registration:**
```python
# Register tools as Trio-native
adapter.register_trio_tool("p2p_workflow_submit")
adapter.register_trio_tool("p2p_task_queue")

# Or as FastAPI-based
adapter.register_fastapi_tool("dataset_load")
```

## Migration Steps

### Step 1: Check MCP++ Availability

First, verify if MCP++ is available in your environment:

```python
from ipfs_datasets_py.mcp_server import mcplusplus

# Check availability
caps = mcplusplus.get_capabilities()
print(f"MCP++ available: {caps['mcplusplus_available']}")

if caps['mcplusplus_available']:
    print("Features available:")
    for feature, available in caps['capabilities'].items():
        print(f"  - {feature}: {available}")
else:
    print("MCP++ not available - using graceful degradation")
    missing = mcplusplus.check_requirements()
    print(f"Missing features: {missing[1]}")
```

### Step 2: Update P2P Service Manager Configuration

Update your P2P service manager initialization to use new features:

**Before (Basic P2P):**
```python
from ipfs_datasets_py.mcp_server.p2p_service_manager import P2PServiceManager

manager = P2PServiceManager(
    enabled=True,
    queue_path="/tmp/p2p_queue"
)
```

**After (Enhanced P2P with MCP++):**
```python
from ipfs_datasets_py.mcp_server.p2p_service_manager import P2PServiceManager

manager = P2PServiceManager(
    enabled=True,
    queue_path="/tmp/p2p_queue",
    # Enable MCP++ features
    enable_workflow_scheduler=True,
    enable_peer_registry=True,
    enable_bootstrap=True,
    # Optional: Custom bootstrap nodes
    bootstrap_nodes=[
        "/ip4/104.131.131.82/tcp/4001/p2p/QmaCpDMGvV2BGHeYERUEnRQAwe3N8SzbUtfsmvsqQLuvuJ"
    ]
)

# Check what's available
caps = manager.get_capabilities()
print(f"P2P enabled: {caps['p2p_enabled']}")
print(f"Workflow scheduler: {caps['workflow_scheduler_available']}")
print(f"Peer registry: {caps['peer_registry_available']}")
```

### Step 3: Access Advanced P2P Features

Use the new accessor methods to work with P2P features:

```python
# Access workflow scheduler
scheduler = manager.get_workflow_scheduler()
if scheduler:
    # Workflow scheduler available
    print("Can submit P2P workflows")
    # await scheduler.submit_workflow(workflow_spec)
else:
    print("Workflow scheduler not available")

# Access peer registry
registry = manager.get_peer_registry()
if registry:
    # Peer registry available
    print("Can discover and connect to peers")
    # peers = await registry.discover_peers()
else:
    print("Peer registry not available")
```

### Step 4: Update Tool Registration (Optional)

If you're creating custom tools, mark them with runtime information:

```python
def my_fastapi_tool(x):
    """Standard FastAPI tool."""
    return x

async def my_trio_tool(x):
    """Trio-native P2P tool."""
    return x

# Mark as Trio-native (optional, can be detected automatically)
my_trio_tool._mcp_runtime = "trio"

# Register with adapter
from ipfs_datasets_py.mcp_server.p2p_mcp_registry_adapter import P2PMCPRegistryAdapter

adapter = P2PMCPRegistryAdapter(server)
adapter.register_trio_tool("my_trio_tool")
adapter.register_fastapi_tool("my_fastapi_tool")

# Query runtime information
tools = adapter.tools
print(f"my_trio_tool runtime: {tools['my_trio_tool']['runtime']}")
print(f"Trio-native: {tools['my_trio_tool']['runtime_metadata']['is_trio_native']}")
```

## Backward Compatibility

**All existing code continues to work unchanged.** The enhancements are fully backward compatible:

✅ **Old P2P service manager usage works:**
```python
# This still works exactly as before
manager = P2PServiceManager(enabled=True, queue_path="/tmp/queue")
```

✅ **Old registry adapter usage works:**
```python
# This still works exactly as before
adapter = P2PMCPRegistryAdapter(server)
tools = adapter.tools
# Old fields still present: function, description, input_schema
```

✅ **New features are opt-in:**
- MCP++ features only activate if explicitly enabled
- Graceful degradation if MCP++ unavailable
- No exceptions or errors in degraded mode

## Graceful Degradation

The system gracefully degrades when MCP++ is not available:

```python
from ipfs_datasets_py.mcp_server import mcplusplus

# These always work, even without MCP++
caps = mcplusplus.get_capabilities()
# Returns: {'mcplusplus_available': False, 'capabilities': {...}}

scheduler = mcplusplus.get_scheduler()
# Returns: None (no exception)

# Service manager works without MCP++
manager = P2PServiceManager(
    enabled=True,
    enable_workflow_scheduler=True  # Will degrade gracefully
)
# Manager created successfully
# has_advanced_features() returns False
# get_workflow_scheduler() returns None
```

## Testing

Validate your migration with the included tests:

```bash
# Run all Phase 1 tests
python -m pytest tests/mcp_server/test_mcplusplus_imports.py -v
python -m pytest tests/mcp_server/test_p2p_registry_adapter.py -v
python -m pytest tests/mcp_server/test_p2p_integration.py -v

# Expected: 62 tests, 100% passing
```

## Configuration Files

Update your YAML configuration to enable new features:

```yaml
# config.yaml
p2p:
  enabled: true
  listen_port: 4001
  queue_path: /tmp/p2p_queue
  
  # MCP++ Advanced Features (Phase 1)
  enable_workflow_scheduler: true
  enable_peer_registry: true
  enable_bootstrap: true
  
  # Optional: Custom bootstrap nodes
  bootstrap_nodes:
    - /ip4/104.131.131.82/tcp/4001/p2p/QmaCpDMGvV2BGHeYERUEnRQAwe3N8SzbUtfsmvsqQLuvuJ
    - /ip4/104.236.179.241/tcp/4001/p2p/QmSoLPppuBtQSGwKDZT2M73ULpjvfd3aZ6ha4oFGL1KrGM
```

## What's Coming Next

**Phase 2: P2P Tool Enhancement** (Coming Soon)
- 20+ new P2P tools (workflow, task queue, peer management)
- 6 workflow tools (submit, status, cancel, list, dependencies, result)
- 14 task queue tools (submit, status, cancel, priority, retry, etc.)
- Peer management tools (discover, connect, disconnect, metrics)

**Phase 3: Performance Optimization**
- Runtime router for optimal performance
- 50-70% latency reduction for P2P operations
- Performance benchmarks and metrics

**Phase 4: Advanced Features**
- Structured concurrency with Trio nurseries
- Workflow dependencies (DAG)
- Task priorities and scheduling
- Result caching

## Troubleshooting

### MCP++ Not Available

**Symptom:** `caps['mcplusplus_available']` returns `False`

**Solutions:**
1. Check if `ipfs_accelerate_py` is installed:
   ```bash
   pip show ipfs-accelerate-py
   ```

2. Verify the mcplusplus_module exists:
   ```bash
   python -c "from ipfs_accelerate_py.mcplusplus_module import trio"
   ```

3. Install if missing:
   ```bash
   pip install git+https://github.com/endomorphosis/ipfs_accelerate_py.git
   ```

### Features Not Working

**Symptom:** `get_workflow_scheduler()` returns `None`

**Check:**
1. Verify MCP++ is available (see above)
2. Ensure features are enabled in configuration:
   ```python
   manager = P2PServiceManager(
       enabled=True,
       enable_workflow_scheduler=True  # Must be True
   )
   ```
3. Check capabilities:
   ```python
   caps = manager.get_capabilities()
   print(caps)  # Shows what's actually available
   ```

### Runtime Detection Issues

**Symptom:** Tools showing wrong runtime

**Solutions:**
1. Explicitly register tools:
   ```python
   adapter.register_trio_tool("tool_name")
   ```

2. Add `_mcp_runtime` marker:
   ```python
   def my_tool():
       pass
   my_tool._mcp_runtime = "trio"
   ```

3. Clear runtime cache if needed:
   ```python
   adapter.clear_runtime_cache()
   ```

## Support

For issues, questions, or feedback:

- **GitHub Issues**: https://github.com/endomorphosis/ipfs_datasets_py/issues
- **Documentation**: See `MCP_IMPROVEMENT_PLAN.md`, `ARCHITECTURE_INTEGRATION.md`
- **Tests**: See `tests/mcp_server/` for examples

## Version History

- **2026-02-17 - Phase 1 Complete**: Foundation with import layer, enhanced service manager, enhanced registry adapter, 62 tests
- **Future - Phase 2**: P2P tool enhancement (20+ tools)
- **Future - Phase 3**: Performance optimization
- **Future - Phase 4**: Advanced features

---

**Last Updated:** 2026-02-17  
**Phase:** 1 (Foundation) - Complete ✅  
**Next:** Phase 2 (P2P Tool Enhancement)
