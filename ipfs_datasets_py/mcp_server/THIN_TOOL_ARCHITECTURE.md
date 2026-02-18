# Thin Tool Architecture Guide

**Date:** 2026-02-18  
**Purpose:** Architectural guidelines for MCP server tools and CLI alignment  
**Related:** [MCP Server Refactoring Plan](./MCP_SERVER_REFACTORING_PLAN_2026.md)

---

## Core Principle: Separation of Concerns

**Business Logic** → Core Modules (`ipfs_datasets_py/*`)  
**Orchestration** → Tools (MCP server + CLI)  
**Interface** → Transport layer (MCP protocol / command line)

### The Golden Rule

> **Tools are thin wrappers. All business logic lives in core modules.**

Tools should typically be **<100 lines** of code, consisting of:
1. Input validation
2. Core module imports
3. Parameter marshalling
4. Core module function calls
5. Response formatting

---

## Architecture Layers

```
┌─────────────────────────────────────────────────────────┐
│  User Interfaces (Third-Party Consumable)              │
├─────────────────────────────────────────────────────────┤
│  CLI (ipfs-datasets)        │  MCP Server Tools        │
│  - Argparse interface       │  - JSON schema interface │
│  - Terminal output          │  - MCP protocol          │
│  - Batch scripts            │  - IDE integration       │
└─────────────┬───────────────┴──────────────┬───────────┘
              │                              │
              ▼                              ▼
┌─────────────────────────────────────────────────────────┐
│  Thin Tool Layer (Orchestration Only)                   │
│  - Parameter validation                                 │
│  - Error handling                                       │
│  - Response formatting                                  │
│  - Core module dispatch                                 │
└─────────────────────┬───────────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────────┐
│  Core Business Logic (Third-Party Reusable)             │
├─────────────────────────────────────────────────────────┤
│  ipfs_datasets_py/                                      │
│  ├── logic/          - FOL, deontic, temporal logic     │
│  ├── search/         - Semantic, similarity search      │
│  ├── processors/     - Data processing, multimedia      │
│  ├── core_operations/- Dataset mgmt, IPFS, graphs       │
│  ├── knowledge_graphs/- Graph databases                 │
│  ├── ml/            - Machine learning pipelines        │
│  └── ...            - Other domain modules              │
└─────────────────────────────────────────────────────────┘
```

---

## Good Example: load_dataset Tool

**File:** `ipfs_datasets_py/mcp_server/tools/dataset_tools/load_dataset.py`  
**Size:** 84 lines  
**Pattern:** ✅ CORRECT

```python
# ipfs_datasets_py/mcp_server/tools/dataset_tools/load_dataset.py
"""
MCP tool for loading datasets.

This is a thin wrapper around the core DatasetLoader class.
Core implementation: ipfs_datasets_py.core_operations.dataset_loader.DatasetLoader
"""

from ipfs_datasets_py.core_operations import DatasetLoader  # ← Core module import

async def load_dataset(
    source: str,
    format: Optional[str] = None,
    options: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """Load a dataset from a source."""
    
    # Minimal validation
    if not source:
        return mcp_error_response("Missing required field: source")
    
    # Call core module - ALL business logic is here
    try:
        loader = DatasetLoader()  # ← Core class
        result = await loader.load(source, format=format, options=options)
        return result
    except Exception as e:
        logger.error(f"Error in load_dataset MCP tool: {e}")
        return {"status": "error", "message": str(e)}
```

**Why this is good:**
- ✅ Imports from core module (`DatasetLoader`)
- ✅ No business logic in tool (just validation + dispatch)
- ✅ Clean error handling
- ✅ Documentation references core implementation
- ✅ Third parties can use `DatasetLoader` directly

---

## Good Example: Search Tools

**File:** `ipfs_datasets_py/mcp_server/tools/search_tools/search_tools.py`  
**Size:** 246 lines (3 tool classes)  
**Pattern:** ✅ CORRECT

```python
from ipfs_datasets_py.search.search_tools_api import (
    semantic_search_from_parameters,  # ← Core functions
    similarity_search_from_parameters,
)

class SemanticSearchTool(ClaudeMCPTool):
    """Tool for performing semantic search."""
    
    async def execute(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        # Validate parameters
        validator.validate_json_schema(parameters, self.input_schema)
        
        # Extract and normalize params
        query = parameters["query"]
        model = parameters.get("model", "default-model")
        top_k = parameters.get("top_k", 5)
        
        # Call core module function - ALL business logic is here
        return await semantic_search_from_parameters(
            vector_service=self.vector_service,
            query=query,
            model=model,
            top_k=top_k,
        )
```

**Why this is good:**
- ✅ Imports core API functions (`search_tools_api`)
- ✅ Validation only (no search logic)
- ✅ Parameter extraction and normalization
- ✅ Direct passthrough to core module
- ✅ Third parties can import `search_tools_api` directly

---

## Anti-Pattern: Thick Tools (AVOID)

```python
# ❌ BAD: Business logic in tool file
async def load_dataset_bad(source: str) -> Dict:
    """BAD: Contains business logic in tool."""
    
    # ❌ File I/O logic in tool
    if source.endswith('.json'):
        with open(source) as f:
            data = json.load(f)
    elif source.endswith('.csv'):
        import pandas as pd
        data = pd.read_csv(source)
    
    # ❌ Processing logic in tool
    data = data[data['value'] > 0]  # Filtering
    data['new_col'] = data['a'] + data['b']  # Computation
    
    # ❌ Validation logic in tool
    if len(data) > 10000:
        raise ValueError("Dataset too large")
    
    return {"data": data}
```

**Why this is bad:**
- ❌ File I/O logic should be in `core_operations/dataset_loader.py`
- ❌ Processing logic should be in `processors/` module
- ❌ Business rules (size limits) should be in core module
- ❌ Third parties can't reuse this logic
- ❌ Hard to test (tightly coupled to MCP interface)
- ❌ Hard to maintain (logic scattered across tools)

---

## Core Module Design Patterns

### Pattern 1: API Functions (Stateless)

**Use when:** Simple operations, no persistent state needed

```python
# ipfs_datasets_py/search/search_tools_api.py
async def semantic_search_from_parameters(
    vector_service,
    query: str,
    model: str,
    top_k: int = 5,
    **kwargs
) -> Dict[str, Any]:
    """
    Perform semantic search.
    
    This is a core API function designed for reuse by:
    - MCP server tools
    - CLI tools  
    - Third-party packages
    """
    # All business logic here
    embeddings = await vector_service.encode(query, model)
    results = await vector_service.search(embeddings, top_k=top_k)
    return format_search_results(results)
```

### Pattern 2: Service Classes (Stateful)

**Use when:** Need to maintain state, configuration, or resources

```python
# ipfs_datasets_py/core_operations/dataset_loader.py
class DatasetLoader:
    """
    Core service for loading datasets.
    
    Designed for reuse by:
    - MCP server tools
    - CLI tools
    - Third-party packages
    """
    
    def __init__(self, config: Optional[Dict] = None):
        self.config = config or self._default_config()
        self._cache = {}
    
    async def load(self, source: str, **options) -> Dict:
        """Load a dataset from source."""
        # All business logic here
        if source in self._cache:
            return self._cache[source]
        
        data = await self._load_from_source(source, **options)
        self._cache[source] = data
        return data
```

### Pattern 3: Integration Modules (Complex Workflows)

**Use when:** Orchestrating multiple services or complex workflows

```python
# ipfs_datasets_py/logic/integration/temporal_deontic_api.py
class TemporalDeonticIntegration:
    """
    Integration layer for temporal-deontic logic.
    
    Coordinates multiple services while remaining reusable.
    """
    
    def __init__(self, fol_service, deontic_service, temporal_service):
        self.fol = fol_service
        self.deontic = deontic_service
        self.temporal = temporal_service
    
    async def process_legal_text(self, text: str) -> Dict:
        """Process legal text through full pipeline."""
        # Orchestration logic (still business logic)
        fol_result = await self.fol.convert(text)
        deontic_result = await self.deontic.analyze(fol_result)
        temporal_result = await self.temporal.add_constraints(deontic_result)
        return self._merge_results(fol_result, deontic_result, temporal_result)
```

---

## CLI-MCP Alignment

### Shared Parameter Definitions

Both CLI and MCP tools should use the same parameter schema where possible:

```python
# ipfs_datasets_py/core_operations/schemas.py
LOAD_DATASET_SCHEMA = {
    "source": {
        "type": "string",
        "required": True,
        "description": "Source identifier of the dataset",
        "cli_arg": "--source",
        "mcp_key": "source"
    },
    "format": {
        "type": "string",
        "required": False,
        "description": "Format of the dataset (json, csv, parquet)",
        "cli_arg": "--format",
        "mcp_key": "format",
        "default": "auto"
    }
}
```

### Unified Validation

```python
# ipfs_datasets_py/core_operations/validation.py
def validate_load_dataset_params(source: str, format: Optional[str] = None):
    """
    Validate dataset loading parameters.
    
    Used by both CLI and MCP tools for consistent validation.
    """
    if not source:
        raise ValueError("source is required")
    
    if format and format not in SUPPORTED_FORMATS:
        raise ValueError(f"Unsupported format: {format}")
    
    return True
```

### Tool Implementation (CLI)

```python
# CLI tool using shared schema and validation
def cli_load_dataset(args):
    """CLI implementation using core modules."""
    # Use shared validation
    validate_load_dataset_params(args.source, args.format)
    
    # Use core service
    loader = DatasetLoader()
    result = loader.load(args.source, format=args.format)
    
    # Format for terminal
    print(json.dumps(result, indent=2))
```

### Tool Implementation (MCP)

```python
# MCP tool using same core modules
async def mcp_load_dataset(parameters: Dict) -> Dict:
    """MCP implementation using core modules."""
    # Use shared validation
    validate_load_dataset_params(
        parameters["source"],
        parameters.get("format")
    )
    
    # Use same core service
    loader = DatasetLoader()
    result = await loader.load(
        parameters["source"],
        format=parameters.get("format")
    )
    
    # Format for MCP protocol
    return {"status": "success", "data": result}
```

---

## Tool Nesting for Context Window Management

### Current: Flat Structure (Hierarchical Tool Manager)

```
tools/
├── admin_tools/
│   ├── tool1.py
│   ├── tool2.py
├── dataset_tools/
│   ├── load_dataset.py
│   ├── save_dataset.py
│   ├── process_dataset.py
├── search_tools/
│   ├── semantic_search.py
│   ├── similarity_search.py
```

**Discovery:**
```bash
# List categories
ipfs-datasets tools list-categories

# List tools in category
ipfs-datasets tools list --category dataset_tools

# Execute tool
ipfs-datasets tools execute dataset_tools.load_dataset --source data.json
```

### Enhanced: Nested Commands (Like Git)

```
dataset/
  load      → core_operations.DatasetLoader.load()
  save      → core_operations.DatasetSaver.save()
  process   → core_operations.DatasetProcessor.process()
  transform/
    filter  → processors.filter()
    map     → processors.map()
    reduce  → processors.reduce()

search/
  semantic  → search.semantic_search()
  similarity→ search.similarity_search()
  faceted   → search.faceted_search()
```

**Nested execution:**
```bash
# Nested command structure
ipfs-datasets dataset load --source data.json
ipfs-datasets dataset transform filter --column age --operator gt --value 18
ipfs-datasets search semantic --query "machine learning"
```

**Advantages:**
- ✅ More intuitive hierarchy
- ✅ Reduces context window (only show relevant subcommands)
- ✅ Aligns with CLI best practices (git, docker, kubectl)
- ✅ Easier discovery (logical grouping)

---

## Guidelines for Tool Developers

### When Creating a New Tool

1. **Start with core module**
   - Implement business logic in appropriate core module
   - Export public API functions/classes
   - Write comprehensive tests for core module

2. **Create thin wrapper**
   - Import from core module
   - Add MCP/CLI-specific validation
   - Marshal parameters to core function
   - Format response for transport layer

3. **Document both layers**
   ```python
   # In tool file
   """
   MCP tool for semantic search.
   
   This is a thin wrapper around semantic_search_from_parameters().
   Core implementation: ipfs_datasets_py.search.search_tools_api
   """
   ```

4. **Test both layers independently**
   - Unit tests for core module
   - Integration tests for tool wrapper
   - E2E tests for full workflow

### Size Guidelines

- **Core modules:** No size limit (all business logic lives here)
- **MCP tools:** Typically <100 lines
- **CLI tools:** Typically <150 lines (includes argparse setup)

### Import Guidelines

**✅ DO:**
```python
from ipfs_datasets_py.core_operations import DatasetLoader
from ipfs_datasets_py.search.search_tools_api import semantic_search
from ipfs_datasets_py.logic.fol import convert_text_to_fol
```

**❌ DON'T:**
```python
from pandas import DataFrame  # Use core module's pandas wrapper
from sklearn import model     # Use core module's ML utilities
import requests              # Use core module's HTTP client
```

### When to Create New Core Modules

Create a new core module when:
- ✅ Functionality is reusable across multiple tools
- ✅ Logic is complex enough to warrant separate testing
- ✅ Third parties might want to use this independently
- ✅ Multiple tools share similar logic

Don't create a new core module when:
- ❌ Logic is tool-specific (validation, formatting)
- ❌ Only used by one tool
- ❌ Trivial helper functions

---

## Migration Strategy

### For Existing Thick Tools

If you find a tool with embedded business logic:

1. **Extract business logic to core module**
   ```python
   # Move from: ipfs_datasets_py/mcp_server/tools/dataset_tools/thick_tool.py
   # Move to: ipfs_datasets_py/core_operations/new_service.py
   ```

2. **Create thin wrapper**
   ```python
   # Replace thick_tool.py with thin wrapper
   from ipfs_datasets_py.core_operations import new_service
   
   async def tool_function(params):
       return await new_service.do_work(params)
   ```

3. **Update tests**
   - Move business logic tests to core module tests
   - Keep integration tests for tool wrapper

4. **Update documentation**
   - Document core module as primary API
   - Mark tool as wrapper in docstring

---

## Third-Party Integration Example

### Before (Thick Tool - Hard to Reuse)

```python
# Third party can't easily reuse this
from ipfs_datasets_py.mcp_server.tools.dataset_tools import load_dataset

# Requires MCP protocol knowledge
result = await load_dataset({"source": "data.json"})  
```

### After (Thin Tool - Easy to Reuse)

```python
# Third party uses core module directly
from ipfs_datasets_py.core_operations import DatasetLoader

# Clean, documented API
loader = DatasetLoader()
result = await loader.load("data.json")

# Can configure as needed
loader = DatasetLoader(config={"cache": True, "timeout": 30})
result = await loader.load("data.json", format="parquet")
```

---

## Checklist for New Tools

- [ ] Business logic implemented in core module (`ipfs_datasets_py/*`)
- [ ] Core module has public API (functions or classes)
- [ ] Core module has comprehensive docstrings
- [ ] Core module has unit tests (>80% coverage)
- [ ] Tool file imports from core module
- [ ] Tool file is <100 lines (excluding schemas)
- [ ] Tool file has docstring referencing core module
- [ ] Tool does validation only (no business logic)
- [ ] Tool marshals parameters to core function
- [ ] Tool formats response for transport layer
- [ ] Integration tests verify tool wrapper works
- [ ] Documentation shows both tool and core module usage

---

## Summary

**The Golden Rules:**

1. **Business logic → Core modules** (`ipfs_datasets_py/*`)
2. **Orchestration → Tools** (MCP server + CLI)
3. **Tools are thin** (<100 lines, validation + dispatch)
4. **Core modules are reusable** (by tools and third parties)
5. **Same core modules** (CLI and MCP use same underlying code)
6. **Nested hierarchy** (for better UX and context management)

**Benefits:**

- ✅ Third parties can reuse core modules directly
- ✅ Tools are easy to maintain (thin = simple)
- ✅ Business logic is tested independently
- ✅ CLI and MCP stay aligned (same core code)
- ✅ Reduced context window usage (hierarchical)
- ✅ Clear separation of concerns

---

**Related Documentation:**
- [MCP Server Refactoring Plan](./MCP_SERVER_REFACTORING_PLAN_2026.md)
- [Hierarchical Tool Manager](./hierarchical_tool_manager.py)
- [Tool Registry](./tool_registry.py)

**Last Updated:** 2026-02-18  
**Status:** Active Guidelines
