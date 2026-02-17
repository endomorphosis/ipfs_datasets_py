# MCP Server Hierarchical Tool Architecture

## Visual Overview

### Before: Flat Tool Registration (Current)
```
┌─────────────────────────────────────────┐
│         MCP Server Context Window        │
│  ┌────────────────────────────────────┐  │
│  │ Tool 1: load_dataset               │  │
│  │ Tool 2: save_dataset               │  │
│  │ Tool 3: convert_dataset_format     │  │
│  │ Tool 4: pin_to_ipfs                │  │
│  │ Tool 5: get_from_ipfs              │  │
│  │ Tool 6: query_knowledge_graph      │  │
│  │ Tool 7-347: ... (340 more tools)   │  │
│  └────────────────────────────────────┘  │
│                                           │
│  ❌ Problems:                             │
│    - Context window completely filled    │
│    - 347 tool definitions sent to LLM    │
│    - Business logic in MCP layer         │
│    - Cannot reuse in CLI or imports      │
└─────────────────────────────────────────┘
```

### After: Hierarchical Tool Management (Target)
```
┌─────────────────────────────────────────────────────────────┐
│              MCP Server Context Window                       │
│  ┌────────────────────────────────────────────────────────┐ │
│  │ Meta-Tool 1: tools_list_categories                     │ │
│  │ Meta-Tool 2: tools_list_tools(category)                │ │
│  │ Meta-Tool 3: tools_get_schema(category, tool)          │ │
│  │ Meta-Tool 4: tools_dispatch(category, tool, params)    │ │
│  └────────────────────────────────────────────────────────┘ │
│                                                               │
│  ✅ Benefits:                                                │
│    - Only 4 tools in context window (99% reduction)         │
│    - Tools loaded dynamically on demand                     │
│    - Business logic in reusable core modules                │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
                ┌──────────────────────────┐
                │ HierarchicalToolManager  │
                └──────────────────────────┘
                              │
        ┌─────────────────────┼─────────────────────┐
        ▼                     ▼                     ▼
   [dataset_tools]       [ipfs_tools]         [graph_tools]
   - load_dataset        - pin_to_ipfs        - query_knowledge_graph
   - save_dataset        - get_from_ipfs      - ...
   - convert_format      - ...
   - ...
        │                     │                     │
        ▼                     ▼                     ▼
   [Core Modules - Reusable Business Logic]
   
   ipfs_datasets_py/       ipfs_datasets_py/       ipfs_datasets_py/
   datasets/               ipfs/                   knowledge_graphs/
   ├── loader.py          ├── pin.py              ├── query.py
   ├── saver.py           ├── get.py              ├── extraction.py
   └── converter.py       └── ...                 └── ...
```

## Interaction Flow

### Step 1: LLM Discovers Categories
```
User: "What tools are available?"
LLM calls: tools_list_categories()

Response:
{
  "categories": [
    {"name": "dataset_tools", "description": "Dataset operations"},
    {"name": "ipfs_tools", "description": "IPFS operations"},
    {"name": "graph_tools", "description": "Knowledge graph operations"},
    ... (48 more)
  ]
}
```

### Step 2: LLM Lists Tools in Category
```
User: "What can I do with datasets?"
LLM calls: tools_list_tools("dataset_tools")

Response:
{
  "tools": [
    {"name": "load_dataset", "description": "Load datasets from various sources"},
    {"name": "save_dataset", "description": "Save datasets to destinations"},
    {"name": "convert_format", "description": "Convert between formats"},
    ... (more tools)
  ]
}
```

### Step 3: LLM Gets Tool Schema (Optional)
```
User: "How do I load a dataset?"
LLM calls: tools_get_schema("dataset_tools", "load_dataset")

Response:
{
  "schema": {
    "name": "load_dataset",
    "parameters": {
      "source": {"type": "str", "required": true},
      "format": {"type": "str", "required": false},
      ...
    }
  }
}
```

### Step 4: LLM Executes Tool
```
User: "Load the squad dataset"
LLM calls: tools_dispatch("dataset_tools", "load_dataset", {"source": "squad"})

Tool wrapper delegates to core:
┌────────────────────────────────────┐
│ MCP Tool (thin wrapper)            │
│ tools/dataset_tools/load_dataset.py│
└────────────────────────────────────┘
                │
                ▼
┌────────────────────────────────────┐
│ Core Module (business logic)       │
│ ipfs_datasets_py/datasets/loader.py│
│                                     │
│ class DatasetLoader:                │
│   async def load(source, **opts):  │
│     # Business logic here           │
│     return result                   │
└────────────────────────────────────┘
                │
                ▼
          [Result returned]
```

## Code Reusability

### Same Core Logic, Three Access Methods

```
┌────────────────────────────────────────────────────────┐
│        Core Business Logic (Single Source of Truth)     │
│              ipfs_datasets_py/datasets/loader.py        │
│                                                          │
│  class DatasetLoader:                                   │
│      async def load(source, format=None, **options):    │
│          # All business logic lives here                │
│          return result                                  │
└────────────────────────────────────────────────────────┘
                            │
            ┌───────────────┼───────────────┐
            ▼               ▼               ▼
     ┌─────────────┐ ┌─────────────┐ ┌──────────────┐
     │ MCP Server  │ │ CLI Tool    │ │ Python Import│
     │             │ │             │ │              │
     │ tools_      │ │ ipfs-       │ │ from ipfs_   │
     │ dispatch()  │ │ datasets    │ │ datasets_py  │
     │             │ │ dataset     │ │ .datasets    │
     │             │ │ load        │ │ import       │
     │             │ │             │ │ DatasetLoader│
     └─────────────┘ └─────────────┘ └──────────────┘
```

## Directory Structure

```
ipfs_datasets_py/
├── mcp_server/
│   ├── hierarchical_tool_manager.py  ← New infrastructure
│   ├── server.py                      ← Update to register 4 meta-tools
│   └── tools/                         ← 51 categories
│       ├── dataset_tools/
│       │   ├── load_dataset.py        ← Thin wrapper
│       │   ├── save_dataset.py        ← Thin wrapper
│       │   └── convert_format.py      ← Thin wrapper
│       ├── ipfs_tools/
│       │   ├── pin_to_ipfs.py         ← Thin wrapper
│       │   └── get_from_ipfs.py       ← Thin wrapper
│       └── ... (49 more categories)
│
├── datasets/                          ← New core module
│   ├── __init__.py
│   ├── loader.py                      ← Business logic
│   ├── saver.py                       ← Business logic
│   └── converter.py                   ← Business logic
│
├── ipfs/                              ← New core module
│   ├── __init__.py
│   ├── pin.py                         ← Business logic
│   └── get.py                         ← Business logic
│
├── knowledge_graphs/                  ← Existing, verify complete
│   ├── query.py
│   ├── extraction.py
│   └── ...
│
└── ... (other core modules)
```

## Tool Template

### MCP Tool (Thin Wrapper)
```python
# ipfs_datasets_py/mcp_server/tools/dataset_tools/load_dataset.py
"""MCP wrapper for dataset loading.

Core implementation: ipfs_datasets_py.datasets.loader.DatasetLoader
"""

async def load_dataset(source: str, format: str = None, **options):
    """Load a dataset from various sources.
    
    Args:
        source: Dataset source (HF name, file, URL, IPFS CID)
        format: Optional format hint
        **options: Additional loading options
    
    Returns:
        Dict with loading results
    """
    from ipfs_datasets_py.datasets.loader import DatasetLoader
    
    loader = DatasetLoader()
    return await loader.load(source, format=format, **options)
```

### Core Module (Business Logic)
```python
# ipfs_datasets_py/datasets/loader.py
"""Dataset loading operations - reusable business logic."""

class DatasetLoader:
    """Load datasets from various sources."""
    
    async def load(self, source: str, format: str = None, **options):
        """Load a dataset.
        
        This core logic is used by:
        - MCP server tools
        - CLI commands
        - Direct Python imports
        """
        # All business logic here
        if source.startswith("http"):
            return await self._load_from_url(source, **options)
        elif source.startswith("ipfs://"):
            return await self._load_from_ipfs(source, **options)
        else:
            return await self._load_from_huggingface(source, **options)
```

## Migration Strategy

### Phase-by-Phase Rollout

```
Phase 1: Infrastructure [COMPLETE] ✅
├── HierarchicalToolManager
├── 4 meta-tools
├── Test suite
└── Demo script

Phase 2: Core Modules [NEXT] 🔄
├── Create datasets/ module
├── Create ipfs/ module
├── Audit existing modules
└── Extract business logic

Phase 3: Tool Migration
├── Convert dataset_tools → thin wrappers
├── Convert ipfs_tools → thin wrappers
├── Convert graph_tools → thin wrappers
└── ... (prioritize by usage)

Phase 4: Integration
├── Update server.py
├── Register 4 meta-tools
├── Remove 347 flat registrations
└── Test end-to-end

Phase 5-8: Features, CLI, Testing, Docs
```

## Benefits Summary

| Aspect | Before | After | Improvement |
|--------|--------|-------|-------------|
| Tools in context | 347 | 4 | 99% reduction |
| Context window usage | ~50-100KB | ~2KB | 96-98% reduction |
| Code reusability | Duplicate logic | Single source | 100% |
| Maintainability | Scattered | Centralized | ✅ |
| Feature exposure | Manual | Systematic | ✅ |
| CLI consistency | Different code | Same code | ✅ |

## Usage Examples

### For LLM Assistants
```
1. List categories: tools_list_categories()
2. Explore category: tools_list_tools("dataset_tools")
3. Get details: tools_get_schema("dataset_tools", "load_dataset")
4. Execute: tools_dispatch("dataset_tools", "load_dataset", {"source": "squad"})
```

### For Developers
```python
# MCP Server
result = await tools_dispatch("dataset_tools", "load_dataset", {...})

# CLI
$ ipfs-datasets dataset load squad

# Python
from ipfs_datasets_py.datasets import DatasetLoader
loader = DatasetLoader()
result = await loader.load("squad")
```

All three methods use the same underlying business logic! 🎉

---

**Architecture Version:** 1.0  
**Date:** 2026-02-17  
**Status:** Phase 1 Complete, Production Ready for Phase 2
