# MCP Server Refactoring Plan

**Status:** Planning Phase  
**Date:** 2026-02-17  
**Issue:** Comprehensive refactoring improvement for `ipfs_datasets_py/mcp_server/`

## Executive Summary

This document outlines a comprehensive refactoring plan for the MCP server to address:
1. **Business logic isolation** - Move all business logic to core `ipfs_datasets_py/` modules
2. **Code reusability** - Ensure CLI, MCP server, and Python imports use the same core logic
3. **Context window management** - Reduce tool count visible to LLMs through hierarchical nesting
4. **Feature alignment** - Expose all recent features (knowledge graphs, etc.) via MCP tools
5. **Code drift prevention** - Align tool implementations with current system behavior

## Current State Analysis

### Tool Statistics
- **51 tool categories** in `ipfs_datasets_py/mcp_server/tools/`
- **347 Python files** implementing various tools
- **Flat structure** - All tools registered at top level in MCP server
- **Mixed architecture** - Some tools delegate to core (good), others contain embedded logic (bad)

### Problems Identified

#### 1. Context Window Overload
With 347+ tools exposed at the top level, LLM context windows are completely filled with tool definitions, leaving little room for actual conversation and reasoning.

**Evidence:**
```python
# server.py registers ~30+ categories directly
self._register_tools_from_subdir(tools_path / "dataset_tools")
self._register_tools_from_subdir(tools_path / "ipfs_tools")
self._register_tools_from_subdir(tools_path / "vector_tools")
# ... 30+ more registrations
```

#### 2. Business Logic in MCP Tools
Some tools contain business logic that should be in core modules.

**Good Pattern (graph_tools):**
```python
# MCP tool is thin wrapper
async def query_knowledge_graph(...):
    from ipfs_datasets_py.knowledge_graphs.query_knowledge_graph import query_knowledge_graph as core_query
    return core_query(...)
```

**Bad Pattern (Some older tools):**
- Complex processing logic embedded in MCP tool files
- Cannot be reused by CLI or Python API without importing MCP-specific code

#### 3. Missing Feature Exposure
Recent knowledge graph features not all exposed:
- `ipfs_datasets_py/knowledge_graphs/` has 24+ subdirectories
- Only 2 tools in `graph_tools/` directory
- Features like transactions, indexing, constraints not exposed

#### 4. No Hierarchical Tool Access
Unlike CLI which has nested commands, MCP tools are flat:

**CLI Structure (Good):**
```bash
ipfs-datasets tools categories           # List categories
ipfs-datasets tools list <category>      # List tools in category  
ipfs-datasets tools run <category> <tool> [args]  # Run specific tool
```

**MCP Structure (Bad):**
```python
# All 347 tools registered at top level
mcp.add_tool(tool_func, name="query_knowledge_graph")
mcp.add_tool(tool_func, name="pdf_extract_entities")
# ... 345 more
```

## Proposed Architecture

### 1. Hierarchical Tool Organization

#### Tool Namespace Structure
```
tools/
├── category.<category_name>  # Category-level tool
│   ├── list                  # List tools in category
│   └── <tool_name>          # Individual tool
└── tools.list_categories     # Top-level category listing
```

#### Access Pattern
```python
# List all categories
await call_tool("tools.list_categories")

# List tools in a category
await call_tool("category.dataset", action="list")

# Run a specific tool
await call_tool("category.dataset.load_dataset", source="squad")

# Alternative: single dispatch tool
await call_tool("tools.dispatch", 
    category="dataset", 
    tool="load_dataset", 
    params={"source": "squad"})
```

### 2. Core Module Organization

All business logic must reside in core modules under `ipfs_datasets_py/`:

```
ipfs_datasets_py/
├── knowledge_graphs/        # Knowledge graph operations
│   ├── query.py            # Query interface
│   ├── extraction.py       # Entity/relationship extraction
│   ├── storage.py          # Persistence layer
│   └── transactions.py     # Transaction management
├── datasets/               # Dataset operations (NEW)
│   ├── loader.py          # Loading logic
│   ├── saver.py           # Saving logic
│   └── converter.py       # Format conversion
├── embeddings/            # Embedding operations
│   ├── generator.py       # Generation logic
│   └── storage.py         # Vector storage
├── pdf_processing/        # PDF operations
│   ├── extractor.py       # Entity extraction
│   └── analyzer.py        # Document analysis
└── ipfs/                  # IPFS operations (NEW)
    ├── pin.py            # Pinning logic
    └── get.py            # Retrieval logic
```

### 3. MCP Tool Layer

MCP tools become thin wrappers:

```python
# ipfs_datasets_py/mcp_server/tools/dataset_tools/load_dataset.py
"""MCP wrapper for dataset loading."""

async def load_dataset(source: str, format: str = None, **options):
    """Load a dataset from various sources.
    
    This is an MCP tool wrapper. Core implementation:
    ipfs_datasets_py.datasets.loader.DatasetLoader
    """
    from ipfs_datasets_py.datasets.loader import DatasetLoader
    
    loader = DatasetLoader()
    return await loader.load(source, format=format, **options)
```

### 4. Hierarchical Tool Manager

New component to manage nested tool access:

```python
# ipfs_datasets_py/mcp_server/tool_manager.py
class HierarchicalToolManager:
    """Manages nested tool categories and reduces context window usage."""
    
    def __init__(self):
        self.categories = {}
        self._discover_tools()
    
    def _discover_tools(self):
        """Auto-discover tools from directory structure."""
        # Load category metadata
        pass
    
    async def list_categories(self) -> List[str]:
        """List all available tool categories."""
        return list(self.categories.keys())
    
    async def list_tools(self, category: str) -> List[Dict[str, Any]]:
        """List tools in a category with minimal metadata."""
        return self.categories[category].list_tools()
    
    async def get_tool_schema(self, category: str, tool: str) -> Dict[str, Any]:
        """Get full schema for a specific tool (only when needed)."""
        return self.categories[category].get_tool_schema(tool)
    
    async def dispatch(self, category: str, tool: str, **params) -> Any:
        """Dispatch to a specific tool."""
        tool_func = self.categories[category].get_tool(tool)
        return await tool_func(**params)
```

### 5. Reduced MCP Registration

Instead of registering 347 tools, register only:
1. `tools.list_categories` - List available categories
2. `tools.list_tools` - List tools in a category
3. `tools.get_schema` - Get schema for a specific tool
4. `tools.dispatch` - Execute a tool by category/name
5. Optional: `category.<name>` - One meta-tool per category (51 tools)

**Result:** 4-55 tools vs 347 tools = ~85-99% reduction in context window usage

## Implementation Phases

### Phase 1: Core Module Creation (Week 1)
**Goal:** Establish core business logic modules

Tasks:
- [ ] Create `ipfs_datasets_py/datasets/` module
  - [ ] `loader.py` - Dataset loading (from load_dataset tool)
  - [ ] `saver.py` - Dataset saving (from save_dataset tool)
  - [ ] `converter.py` - Format conversion (from convert_dataset_format tool)
- [ ] Create `ipfs_datasets_py/ipfs/` module
  - [ ] `pin.py` - IPFS pinning logic (from pin_to_ipfs tool)
  - [ ] `get.py` - IPFS retrieval (from get_from_ipfs tool)
- [ ] Audit existing modules for completeness
  - [ ] `knowledge_graphs/` - Verify all features exposed
  - [ ] `pdf_processing/` - Verify all features exposed
  - [ ] `embeddings/` - Verify all features exposed

### Phase 2: Hierarchical Tool Manager (Week 1-2)
**Goal:** Build infrastructure for nested tool access

Tasks:
- [ ] Create `ipfs_datasets_py/mcp_server/tool_manager.py`
  - [ ] `HierarchicalToolManager` class
  - [ ] Auto-discovery from tool directories
  - [ ] Category metadata system
- [ ] Create tool category descriptors
  - [ ] `tools/dataset_tools/category.json` - Metadata
  - [ ] Similar for all 51 categories
- [ ] Implement dispatch mechanism
  - [ ] Dynamic tool loading
  - [ ] Parameter validation
  - [ ] Error handling

### Phase 3: Tool Migration (Week 2-3)
**Goal:** Convert existing tools to thin wrappers

Priority order:
1. **High-usage tools** (dataset, ipfs, graph, pdf)
2. **Tools with embedded logic** (need extraction)
3. **Tools already correct** (verify only)
4. **Legacy tools** (deprecate or migrate)

Tasks per tool:
- [ ] Extract business logic to core module
- [ ] Convert MCP tool to thin wrapper
- [ ] Update imports and dependencies
- [ ] Add tests for core module
- [ ] Add tests for MCP wrapper
- [ ] Update documentation

### Phase 4: MCP Server Updates (Week 3)
**Goal:** Integrate hierarchical tool manager

Tasks:
- [ ] Update `server.py`
  - [ ] Remove flat tool registration
  - [ ] Add HierarchicalToolManager
  - [ ] Register 4 meta-tools or 51 category tools
- [ ] Update error handling
- [ ] Update monitoring/analytics
- [ ] Update documentation

### Phase 5: CLI Integration (Week 3-4)
**Goal:** Ensure CLI uses same core modules

Tasks:
- [ ] Update `ipfs_datasets_cli.py`
  - [ ] Use core modules directly (not via MCP)
  - [ ] Maintain nested command structure
- [ ] Update `scripts/cli/` tools
  - [ ] Migrate to use core modules
- [ ] Verify backward compatibility

### Phase 6: Knowledge Graph Feature Exposure (Week 4)
**Goal:** Expose all recent knowledge graph features

Tasks:
- [ ] Audit `knowledge_graphs/` for unexposed features
  - [ ] Transactions (`transactions/`)
  - [ ] Indexing (`indexing/`)
  - [ ] Constraints (`constraints/`)
  - [ ] Cross-document features
  - [ ] SPARQL query templates
- [ ] Create MCP tools for new features
  - [ ] `graph_tools/create_transaction.py`
  - [ ] `graph_tools/create_index.py`
  - [ ] `graph_tools/add_constraint.py`
  - [ ] etc.
- [ ] Update documentation

### Phase 7: Testing & Validation (Week 4-5)
**Goal:** Comprehensive testing of refactored system

Tasks:
- [ ] Unit tests for core modules
- [ ] Integration tests for MCP tools
- [ ] End-to-end tests for CLI
- [ ] Performance testing
  - [ ] Context window usage measurement
  - [ ] Tool dispatch latency
- [ ] Backward compatibility tests

### Phase 8: Documentation & Migration (Week 5)
**Goal:** Document changes and provide migration guide

Tasks:
- [ ] Update API documentation
- [ ] Create migration guide for users
- [ ] Update MCP server README
- [ ] Create example usage documentation
- [ ] Deprecation notices for old patterns

## Design Decisions

### Decision 1: Dispatch Mechanism

**Option A: Single Dispatch Tool**
```python
await tools.dispatch(category="dataset", tool="load_dataset", params={...})
```
- Pros: Minimal context window (1 tool), simple
- Cons: Two-step process (list then dispatch)

**Option B: Category Meta-Tools**
```python
await category.dataset(action="load_dataset", params={...})
```
- Pros: More intuitive, familiar pattern
- Cons: 51 tools instead of 4

**Decision:** Start with Option A, add Option B if needed
- Provides maximum context window savings
- Can add category tools later for convenience
- Most similar to CLI nested structure

### Decision 2: Core Module Structure

**Option A: Feature-based** (Chosen)
```
ipfs_datasets_py/datasets/
ipfs_datasets_py/ipfs/
```

**Option B: Domain-based**
```
ipfs_datasets_py/operations/dataset_ops.py
ipfs_datasets_py/operations/ipfs_ops.py
```

**Decision:** Option A (Feature-based)
- Matches existing structure (knowledge_graphs, pdf_processing)
- Better code organization
- Easier to navigate

### Decision 3: Backward Compatibility

**Approach:** Phased deprecation
1. Keep old tools working during migration (Phase 1-4)
2. Add deprecation warnings (Phase 5)
3. Remove old tools in next major version

## Success Metrics

1. **Context Window Usage**
   - Current: ~347 tools registered
   - Target: 4-55 tools registered
   - Improvement: 85-99% reduction

2. **Code Reusability**
   - Current: Mixed (some tools have embedded logic)
   - Target: 100% of business logic in core modules
   - Metric: Zero business logic in MCP tool files

3. **Feature Coverage**
   - Current: Knowledge graph features partially exposed
   - Target: 100% of core features exposed
   - Metric: All modules in core package have MCP tools

4. **Test Coverage**
   - Current: Varies by module
   - Target: >80% coverage for core modules
   - Target: >80% coverage for MCP wrappers

5. **Performance**
   - Current: Direct tool registration
   - Target: <50ms dispatch overhead
   - Metric: Tool dispatch latency measurement

## Risk Mitigation

### Risk 1: Breaking Changes
**Mitigation:** 
- Maintain backward compatibility during migration
- Deprecation warnings before removal
- Comprehensive testing

### Risk 2: Dispatch Overhead
**Mitigation:**
- Implement efficient tool caching
- Lazy loading of tool schemas
- Performance testing

### Risk 3: Incomplete Migration
**Mitigation:**
- Prioritize high-usage tools
- Incremental rollout
- Automated testing

### Risk 4: User Confusion
**Mitigation:**
- Clear documentation
- Migration guide
- Example usage
- Deprecation warnings with upgrade instructions

## Next Steps

1. **Review & Approval** - Get feedback on this plan
2. **Phase 1 Start** - Begin core module creation
3. **Pilot Tool** - Migrate one tool end-to-end as proof of concept
4. **Full Migration** - Execute all phases

## Appendix A: Tool Categories

Current 51 categories in `ipfs_datasets_py/mcp_server/tools/`:

1. admin_tools (3 files)
2. alert_tools (2 files)
3. analysis_tools (1 file)
4. audit_tools (4 files)
5. auth_tools (3 files)
6. background_task_tools (3 files)
7. bespoke_tools (8 files)
8. cache_tools (2 files)
9. cli (3 files)
10. dashboard_tools (2 files)
11. data_processing_tools (1 file)
12. dataset_tools (17 files)
13. development_tools (18 files)
14. discord_tools (5 files)
15. email_tools (4 files)
16. embedding_tools (10 files)
17. file_converter_tools (9 files)
18. file_detection_tools (4 files)
19. finance_data_tools (6 files)
20. functions (2 files)
21. geospatial_tools (2 files)
22. graph_tools (2 files)
23. index_management_tools (2 files)
24. investigation_tools (6 files)
25. ipfs_cluster_tools (1 file)
26. ipfs_tools (4 files)
27. legacy_mcp_tools (33 files)
28. legal_dataset_tools (30 files)
29. lizardperson_argparse_programs (46 files)
30. lizardpersons_function_tools (15 files)
31. logic_tools (many files)
32. media_tools (many files)
33. medical_research_scrapers (many files)
34. monitoring_tools (many files)
35. p2p_workflow_tools (many files)
36. pdf_tools (many files)
37. provenance_tools (many files)
38. rate_limiting_tools (many files)
39. search_tools (many files)
40. security_tools (many files)
41. session_tools (many files)
42. software_engineering_tools (many files)
43. sparse_embedding_tools (many files)
44. storage_tools (many files)
45. vector_store_tools (many files)
46. vector_tools (many files)
47. web_archive_tools (many files)
48. web_scraping_tools (many files)
49. workflow_tools (many files)
50. (and more...)

**Recommendation:** Consolidate some categories to reduce to ~30-35 meaningful categories.

## Appendix B: Example Core Module Template

```python
# ipfs_datasets_py/datasets/loader.py
"""Dataset loading operations.

This module contains the core business logic for loading datasets
from various sources (Hugging Face, local files, IPFS, etc.).

This logic is used by:
- MCP server tools (via mcp_server/tools/dataset_tools/)
- CLI tools (via ipfs_datasets_cli.py)
- Direct Python imports (by other packages)
"""

from typing import Dict, Any, Optional, Union
from pathlib import Path

class DatasetLoader:
    """Load datasets from various sources."""
    
    def __init__(self):
        self.cache = {}
    
    async def load(
        self,
        source: str,
        format: Optional[str] = None,
        **options
    ) -> Dict[str, Any]:
        """Load a dataset from a source.
        
        Args:
            source: Dataset source (HF name, file path, URL, IPFS CID)
            format: Format hint (json, csv, parquet, etc.)
            **options: Additional loading options
            
        Returns:
            Dict with status, dataset_id, metadata, summary
            
        Raises:
            ValueError: Invalid source or format
            IOError: Failed to load dataset
        """
        # Core loading logic here
        pass
    
    async def load_from_huggingface(self, name: str, **options):
        """Load from Hugging Face Hub."""
        pass
    
    async def load_from_file(self, path: Path, format: str, **options):
        """Load from local file."""
        pass
    
    async def load_from_ipfs(self, cid: str, **options):
        """Load from IPFS."""
        pass
```

## Appendix C: Example MCP Tool Template

```python
# ipfs_datasets_py/mcp_server/tools/dataset_tools/load_dataset.py
"""MCP tool wrapper for dataset loading.

Development pattern:
- Core functionality lives in ipfs_datasets_py.datasets.loader
- This is a thin wrapper that validates args and delegates

Core implementation: ipfs_datasets_py.datasets.loader.DatasetLoader
"""

from typing import Dict, Any, Optional
import logging

logger = logging.getLogger(__name__)

async def load_dataset(
    source: str,
    format: Optional[str] = None,
    **options
) -> Dict[str, Any]:
    """Load a dataset from various sources.
    
    MCP tool for loading datasets. Delegates to core implementation.
    
    Args:
        source: Dataset source identifier
        format: Optional format hint
        **options: Additional loading options
        
    Returns:
        Dict with loading results
    """
    from ipfs_datasets_py.datasets.loader import DatasetLoader
    
    try:
        loader = DatasetLoader()
        result = await loader.load(source, format=format, **options)
        return {
            "status": "success",
            **result
        }
    except Exception as e:
        logger.error(f"Failed to load dataset: {e}")
        return {
            "status": "error",
            "error": str(e)
        }
```

---

**Document Version:** 1.0  
**Last Updated:** 2026-02-17  
**Author:** GitHub Copilot  
**Status:** Draft - Awaiting Review
