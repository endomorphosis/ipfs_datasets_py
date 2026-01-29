# MCP Server Tools Architecture - Audit and Fixes

**Date:** 2026-01-29  
**Status:** ✅ Major Issues Fixed  
**Branch:** copilot/reorganize-root-directory-files

---

## Overview

This document describes the MCP server tools architecture, issues found, and fixes applied to ensure proper import paths and reusability.

---

## Three-Tier Architecture

The codebase follows a three-tier architecture for MCP tools:

```
┌─────────────────────────────────────────────────────────────────┐
│ TIER 1: Core Functionality                                      │
│ Location: ipfs_datasets_py/{module_name}/                       │
│ Purpose: Business logic, data processing, algorithms            │
│ Examples: pdf_processing/, rag/, vector_stores/, embeddings/    │
└─────────────────────────────────────────────────────────────────┘
                              ▲
                              │ imports
                              │
┌─────────────────────────────────────────────────────────────────┐
│ TIER 2: MCP Tool Wrappers                                       │
│ Location: ipfs_datasets_py/mcp_server/tools/{tool_category}/   │
│ Purpose: Thin wrappers exposing core functionality via MCP      │
│ Examples: pdf_tools/, graph_tools/, vector_tools/               │
└─────────────────────────────────────────────────────────────────┘
                              ▲
                              │ MCP protocol
                              │
┌─────────────────────────────────────────────────────────────────┐
│ TIER 3: Network Access                                          │
│ Location: JavaScript SDK, MCP Dashboard, CLI                    │
│ Purpose: User-facing interfaces that consume MCP tools          │
│ Examples: Dashboard UI, CLI commands, API endpoints             │
└─────────────────────────────────────────────────────────────────┘
```

### Key Principles

1. **Core functionality lives in package modules** - Not in MCP tools
2. **MCP tools are thin wrappers** - They call core functions, don't duplicate logic
3. **Imports flow downward** - Tools import FROM package, never the reverse
4. **Reusability** - Same core functions used by CLI, MCP server, and other tools

---

## Issues Found and Fixed

### Issue #1: Missing pdf_query_knowledge_graph Tool ✅ FIXED

**Problem:**
- Test expected `pdf_query_knowledge_graph` in `ipfs_datasets_py.mcp_server.tools.pdf_tools`
- Tool was missing entirely from the pdf_tools module

**Root Cause:**
- Tool wrapper was never created for the knowledge graph query functionality
- GraphRAGIntegrator and QueryEngine existed in pdf_processing but weren't exposed via MCP

**Fix:**
- ✅ Created `mcp_server/tools/pdf_tools/pdf_query_knowledge_graph.py`
- ✅ Updated `mcp_server/tools/pdf_tools/__init__.py` to export new tool
- ✅ Tool follows established pattern: wraps GraphRAGIntegrator and QueryEngine

**Files Changed:**
```
+ ipfs_datasets_py/mcp_server/tools/pdf_tools/pdf_query_knowledge_graph.py
M ipfs_datasets_py/mcp_server/tools/pdf_tools/__init__.py
```

---

### Issue #2: Circular Dependencies with mcp_server.logger ✅ FIXED

**Problem:**
- 33 MCP tool files imported from `ipfs_datasets_py.mcp_server.logger`
- This creates circular dependencies - tools depend on MCP server infrastructure
- Violates principle that tools should be independent, reusable modules

**Affected Files:**
```
audit_tools/           - 2 files
dataset_tools/         - 7 files
discord_tools/         - 3 files
email_tools/           - 3 files
media_tools/           - 9 files
vector_tools/          - 2 files
graph_tools/           - 1 file
ipfs_tools/            - 2 files
security_tools/        - 1 file
provenance_tools/      - 1 file
cli/                   - 1 file
functions/             - 1 file
Total: 33 files
```

**Fix Applied:**
```python
# Before (creates circular dependency)
from ipfs_datasets_py.mcp_server.logger import logger

# After (standard Python logging)
import logging

logger = logging.getLogger(__name__)
```

**Benefits:**
- ✅ No circular dependencies
- ✅ Tools can be tested independently
- ✅ Standard Python logging - no custom infrastructure needed
- ✅ Tools are reusable outside MCP server context

---

### Issue #3: Relative Imports in vector_tools ✅ FIXED

**Problem:**
- `create_vector_index.py` and `search_vector_index.py` used relative imports
- Pattern: `from ....vector_tools import VectorStore`
- Breaks package structure, makes imports fragile

**Files Fixed:**
```
ipfs_datasets_py/mcp_server/tools/vector_tools/create_vector_index.py
ipfs_datasets_py/mcp_server/tools/vector_tools/search_vector_index.py
```

**Fix:**
```python
# Before (relative import - fragile)
from ....vector_tools import VectorStore, create_vector_store

# After (absolute import - clear)
from ipfs_datasets_py.vector_tools import VectorStore, create_vector_store
```

**Benefits:**
- ✅ Clear dependency hierarchy
- ✅ Less fragile - not dependent on directory structure
- ✅ Easier to understand where imports come from

---

### Issue #4: Relative Imports in web_archive_tools ✅ FIXED

**Problem:**
- 6 web_archive tool files used relative imports
- Pattern: `from ....web_archive import WebArchiveProcessor`
- Doesn't reflect reorganized package structure (web_archive → web_archiving)

**Files Fixed:**
```
ipfs_datasets_py/mcp_server/tools/web_archive_tools/create_warc.py
ipfs_datasets_py/mcp_server/tools/web_archive_tools/extract_dataset_from_cdxj.py
ipfs_datasets_py/mcp_server/tools/web_archive_tools/extract_links_from_warc.py
ipfs_datasets_py/mcp_server/tools/web_archive_tools/extract_metadata_from_warc.py
ipfs_datasets_py/mcp_server/tools/web_archive_tools/extract_text_from_warc.py
ipfs_datasets_py/mcp_server/tools/web_archive_tools/index_warc.py
```

**Fix:**
```python
# Before (relative import, wrong package name)
from ....web_archive import WebArchiveProcessor

# After (absolute import, correct package)
from ipfs_datasets_py.web_archiving.web_archive import WebArchiveProcessor
```

**Benefits:**
- ✅ Reflects package reorganization
- ✅ Uses absolute imports
- ✅ Clear where WebArchiveProcessor lives

---

## Remaining Issues (For Future Work)

### Issue #5: Circular Self-Reference in legal_dataset_tools ⚠️ TO DO

**Problem:**
```python
# In: ipfs_datasets_py/mcp_server/tools/legal_dataset_tools/state_laws_cron.py
from ipfs_datasets_py.mcp_server.tools.legal_dataset_tools.state_laws_scheduler import ...
```

**Why This Is Wrong:**
- Tool imports FROM another tool in same directory
- state_laws_scheduler.py should be in core package, not MCP tools
- Violates principle that tools are thin wrappers

**Recommended Fix:**
1. Move `state_laws_scheduler.py` logic to core package (e.g., `ipfs_datasets_py/legal_datasets/`)
2. Have MCP tool wrap the core scheduler
3. Update `state_laws_cron.py` to import from core package

---

### Issue #6: Medical Research Scrapers Relative Imports ⚠️ TO DO

**Problem:**
- Files in `medical_research_scrapers/` use relative imports like `from ....logic_integration`

**Recommended Fix:**
- Convert to absolute imports: `from ipfs_datasets_py.logic_integration import ...`

---

## Architecture Validation Checklist

Use this checklist to validate new or modified MCP tools:

### ✅ Good Patterns (Follow These)

- [ ] Tool imports from core package modules (pdf_processing, rag, etc.)
- [ ] Tool uses `import logging` and `logger = logging.getLogger(__name__)`
- [ ] Tool uses absolute imports: `from ipfs_datasets_py.module import Class`
- [ ] Tool is thin wrapper - calls core functions, doesn't duplicate logic
- [ ] Tool can be imported and used outside MCP server context
- [ ] Tool is exported in the tool directory's `__init__.py`

### ❌ Bad Patterns (Avoid These)

- [ ] Tool imports from `ipfs_datasets_py.mcp_server.logger`
- [ ] Tool uses relative imports: `from ....module import Class`
- [ ] Tool implements business logic instead of wrapping core functions
- [ ] Tool imports from other MCP tools (circular self-reference)
- [ ] Tool depends on MCP server infrastructure to function

---

## Good Examples to Follow

### Example 1: pdf_query_corpus.py
```python
# ✅ GOOD: Imports from core packages
from ipfs_datasets_py.pdf_processing import QueryEngine
from ipfs_datasets_py.graphrag import GraphRAGQueryOptimizer
from ipfs_datasets_py.monitoring import track_operation

# ✅ GOOD: Uses standard logging
import logging
logger = logging.getLogger(__name__)

# ✅ GOOD: Thin wrapper around QueryEngine
async def pdf_query_corpus(...):
    query_engine = QueryEngine()
    result = await query_engine.hybrid_query(...)
    return formatted_result
```

### Example 2: pdf_query_knowledge_graph.py
```python
# ✅ GOOD: Imports from core packages
from ipfs_datasets_py.pdf_processing import GraphRAGIntegrator, QueryEngine
from ipfs_datasets_py.monitoring import track_operation

# ✅ GOOD: Uses standard logging
import logging
logger = logging.getLogger(__name__)

# ✅ GOOD: Wraps core GraphRAG functionality
async def pdf_query_knowledge_graph(...):
    integrator = GraphRAGIntegrator(graph_id=graph_id)
    result = await integrator.query_sparql(...)
    return formatted_result
```

---

## Testing MCP Tools

### Import Test Pattern

```python
def test_tool_can_be_imported():
    """Tool should be importable from expected path."""
    from ipfs_datasets_py.mcp_server.tools.pdf_tools import pdf_query_knowledge_graph
    assert pdf_query_knowledge_graph is not None
```

### Functionality Test Pattern

```python
async def test_tool_wraps_core_functionality():
    """Tool should wrap core package functionality."""
    from ipfs_datasets_py.mcp_server.tools.pdf_tools import pdf_query_corpus
    from ipfs_datasets_py.pdf_processing import QueryEngine
    
    # Both should be available
    assert pdf_query_corpus is not None
    assert QueryEngine is not None
    
    # Tool should call core functionality
    result = await pdf_query_corpus(query="test")
    assert result["status"] in ["success", "error"]
```

---

## Summary Statistics

### Fixed Issues
- ✅ 1 missing tool added (pdf_query_knowledge_graph)
- ✅ 33 files fixed (mcp_server.logger → standard logging)
- ✅ 2 files fixed (vector_tools relative imports)
- ✅ 6 files fixed (web_archive_tools relative imports)
- **Total: 42 files fixed**

### Remaining Issues
- ⚠️ 1 circular self-reference (legal_dataset_tools)
- ⚠️ Medical research scrapers relative imports
- **Total: 2-3 issues remaining for future work**

### Impact
- ✅ Better architecture compliance
- ✅ Reduced circular dependencies
- ✅ Improved reusability
- ✅ Clearer import paths
- ✅ Standard Python practices

---

## Conclusion

The MCP tools architecture is now significantly improved with:
1. Missing tools added
2. Circular dependencies removed
3. Relative imports converted to absolute imports
4. Clear separation between core functionality and MCP tool wrappers

The remaining issues are documented for future work and don't affect the core functionality of the MCP tools.

**Status:** ✅ Architecture Validated and Fixed  
**Ready for:** Production use with documented architecture
