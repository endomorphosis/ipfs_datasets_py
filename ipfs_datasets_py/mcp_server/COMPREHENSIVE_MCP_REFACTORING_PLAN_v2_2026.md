# Comprehensive MCP Server Refactoring and Improvement Plan v2.0

**Date:** 2026-02-19  
**Status:** ACTIVE - Ready for Implementation  
**Branch:** copilot/refactor-improve-mcp-server  
**Priority:** HIGH (Production Readiness & Code Quality)

---

## Executive Summary

This comprehensive refactoring plan provides a complete roadmap for improving the `ipfs_datasets_py/mcp_server` directory to achieve production readiness, code quality excellence, and architectural consistency. Building on the successful completion of Phase 1 (Security) and Phase 2 Weeks 3-5 (Architecture), this plan outlines the remaining work needed to reach 75%+ test coverage, eliminate all code quality issues, and complete the thin tool architecture migration.

### Current State (2026-02-19)

**Achievements:**
- ✅ Phase 1 Security: 5 critical vulnerabilities FIXED
- ✅ Phase 2 Week 3: Global singletons refactored (ServerContext pattern)
- ✅ Phase 2 Week 4: Circular dependencies eliminated (Protocol pattern)
- ✅ Phase 2 Week 5: Duplicate registration fixed (99% overhead reduction)
- ✅ 64 tests passing across all MCP test suites
- ✅ 190KB+ documentation created (10 comprehensive docs)
- ✅ Zero breaking changes, 100% backward compatible

**Metrics:**
- **Codebase Size:** 428 Python files, ~25,000 LOC
- **Tool Categories:** 50 categories, 321 tool files
- **Test Coverage:** ~18-20% (5,597 LOC tests)
- **Phase 2 Progress:** 69% (31/45 hours, Weeks 3-5 complete)
- **Documentation:** 190KB+ (10 documents)

### Critical Issues Remaining

🔴 **HIGH PRIORITY (Code Quality & Testing)**
1. Complex functions with >100 lines (p2p_mcp_registry_adapter.py:126-240)
2. Bare exception handlers masking errors (10+ instances)
3. Missing test coverage for core modules (server.py, hierarchical_tool_manager.py)
4. Type hint inconsistencies (Optional[] missing)
5. Missing docstrings on public APIs

🟡 **MEDIUM PRIORITY (Architecture & Performance)**
6. Thick tools needing refactoring (3 tools: 8-12 hours)
7. Closure variable capture bugs (p2p_mcp_registry_adapter.py)
8. asyncio.run() called from running event loops
9. Missing input validation on API endpoints
10. Duplicate code patterns across tool categories

🟢 **LOW PRIORITY (Maintainability)**
11. Complex import error handling (server.py:26-102)
12. Inconsistent error handling patterns
13. TODOs in production code (15+ instances)
14. Documentation gaps (40% → 90% target)

### Improvement Targets

| Metric | Current | Phase 2 Target | Phase 3 Target | Timeline |
|--------|---------|----------------|----------------|----------|
| Test Coverage | ~18-20% | 35-40% | 75%+ | Weeks 6-7 |
| Code Quality Issues | 50+ | 15-20 | <5 | Weeks 6-8 |
| Complex Functions (>100 lines) | 8 | 3 | 0 | Week 6 |
| Bare Exceptions | 10+ | 0 | 0 | Week 6 |
| Missing Docstrings | 120+ | 30 | 0 | Weeks 7-8 |
| Performance Bottlenecks | 8 | 3 | 0 | Week 9 |

### Strategic Goals

1. **Complete Phase 2 (Weeks 6-7)** - Architecture improvements and thick tool refactoring
2. **Launch Phase 3 (Weeks 7-10)** - Core testing infrastructure and 75%+ coverage
3. **Code Quality Excellence** - Zero critical issues, comprehensive documentation
4. **Performance Optimization** - 50-70% latency reduction where applicable
5. **Production Readiness** - Full test coverage, monitoring, validated deployment

---

## Table of Contents

1. [Current State Analysis](#1-current-state-analysis)
2. [Architecture Overview](#2-architecture-overview)
3. [Critical Issues Breakdown](#3-critical-issues-breakdown)
4. [Phase 2 Completion Plan (Weeks 6-7)](#4-phase-2-completion-plan-weeks-6-7)
5. [Phase 3 Testing Strategy (Weeks 7-10)](#5-phase-3-testing-strategy-weeks-7-10)
6. [Code Quality Improvement Roadmap](#6-code-quality-improvement-roadmap)
7. [Performance Optimization Plan](#7-performance-optimization-plan)
8. [Documentation Strategy](#8-documentation-strategy)
9. [Testing Infrastructure](#9-testing-infrastructure)
10. [Success Metrics & KPIs](#10-success-metrics--kpis)
11. [Risk Management](#11-risk-management)
12. [Implementation Timeline](#12-implementation-timeline)

---

## 1. Current State Analysis

### 1.1 Codebase Metrics

**Structure:**
```
ipfs_datasets_py/mcp_server/
├── Core Server (15 files, ~4,500 LOC)
│   ├── server.py (926 lines)
│   ├── hierarchical_tool_manager.py (536 lines)
│   ├── fastapi_service.py (1,152 lines)
│   ├── tool_registry.py, tool_metadata.py
│   └── server_context.py, mcp_interfaces.py (NEW)
├── MCP++ Integration (11 files, ~2,000 LOC)
│   ├── mcplusplus/ (workflow, task queue, peer registry)
│   ├── p2p_service_manager.py
│   └── p2p_mcp_registry_adapter.py
├── Tools (321 files, ~18,000 LOC)
│   ├── 50 categories (admin, analysis, dataset, etc.)
│   └── 48 tool classes implementing ClaudeMCPTool
├── Utils & Config (12 files, ~1,200 LOC)
├── Benchmarks (5 files, ~800 LOC)
└── Documentation (26 MD files, 190KB+)
```

**Test Coverage:**
- Total test LOC: 5,597 lines
- Test files: 15+ files in tests/mcp/
- Coverage estimate: 18-20%
- Key gaps: server.py, hierarchical_tool_manager.py, fastapi_config.py

**Quality Metrics:**
- Complex functions (>100 lines): 8
- Bare exception handlers: 10+
- Missing docstrings: 120+
- TODOs/FIXMEs: 15+
- Type hint issues: 30+

### 1.2 Phase Completion Status

**Phase 1: Security Hardening ✅ (100% Complete)**
- All 5 critical vulnerabilities fixed
- Hardcoded secrets eliminated
- Bare exceptions in critical paths fixed
- Subprocess sanitization implemented
- Error report sanitization added

**Phase 2: Architecture Improvements (69% Complete)**
- ✅ Week 3: Global singleton refactoring (ServerContext)
- ✅ Week 4: Circular dependency elimination (Protocol pattern)
- ✅ Week 5: Duplicate registration removal (377→4 registrations)
- ⏳ Week 6: Thick tool refactoring (PLANNED, 8-12 hours)
- ⏳ Week 7: Phase 3 core testing start (PLANNED, 20-25 hours)

**Phase 3: Testing Infrastructure (0% Complete)**
- Target: 75%+ coverage, 170-210 tests
- Core modules: server.py (40-50 tests), hierarchical_tool_manager.py (20-25 tests)
- FastAPI: fastapi_config.py (10-15 tests)
- P2P Integration: 8-10 tests
- Total estimate: 20-25 hours (Weeks 7-10)

### 1.3 Tool Ecosystem Analysis

**Tool Categories (50 total):**
- admin_tools, alert_tools, analysis_tools, audit_tools, auth_tools
- background_task_tools, bespoke_tools, cache_tools, dashboard_tools
- data_processing_tools, dataset_tools, development_tools, discord_tools
- email_tools, embedding_tools, file_converter_tools, file_detection_tools
- finance_data_tools, geospatial_tools, graph_tools, index_management_tools
- investigation_tools, ipfs_cluster_tools, ipfs_tools, legal_dataset_tools
- logic_tools, media_tools, medical_research_scrapers, monitoring_tools
- p2p_tools, p2p_workflow_tools, pdf_tools, provenance_tools
- rate_limiting_tools, search_tools, security_tools, session_tools
- software_engineering_tools, sparse_embedding_tools, storage_tools
- vector_store_tools, vector_tools, web_archive_tools, web_scraping_tools
- workflow_tools, and more...

**Thin vs Thick Tools:**
- Thin wrappers (<150 lines): 85% (273 tools)
- Partial compliance: 10% (32 tools)
- Thick tools (>300 lines): 5% (16 tools)

**Week 6 Refactoring Targets:**
1. **enhanced_ipfs_cluster_tools.py** (800+ lines → ~150 lines)
2. **geospatial_analysis_tools.py** (600+ lines → ~120 lines)
3. **web_archive/common_crawl_tools.py** (500+ lines → ~100 lines)

---

## 2. Architecture Overview

### 2.1 Layered Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    MCP Server Layer                     │
│  server.py, standalone_server.py, fastapi_service.py   │
│  - Tool registration and dispatch                      │
│  - Request validation and routing                      │
│  - Error handling and logging                          │
└──────────────────┬──────────────────────────────────────┘
                   │
┌──────────────────▼──────────────────────────────────────┐
│              Tool Management Layer                      │
│  hierarchical_tool_manager.py, tool_registry.py        │
│  tool_metadata.py, server_context.py                   │
│  - Tool discovery and loading                          │
│  - Hierarchical organization                           │
│  - Metadata management                                 │
└──────────────────┬──────────────────────────────────────┘
                   │
┌──────────────────▼──────────────────────────────────────┐
│                 P2P/MCP++ Layer                         │
│  p2p_service_manager.py, p2p_mcp_registry_adapter.py   │
│  mcplusplus/ (workflow, task_queue, peer_registry)     │
│  - P2P tool registration                               │
│  - Workflow orchestration                              │
│  - Distributed task execution                          │
└──────────────────┬──────────────────────────────────────┘
                   │
┌──────────────────▼──────────────────────────────────────┐
│                   Tools Layer                           │
│  tools/ (50 categories, 321 tool files)                │
│  - Thin wrappers (<150 lines)                          │
│  - Standard ClaudeMCPTool pattern                      │
│  - Core module delegation                              │
└──────────────────┬──────────────────────────────────────┘
                   │
┌──────────────────▼──────────────────────────────────────┐
│                  Core Modules Layer                     │
│  ipfs_datasets_py/ (embeddings, pdf_processing, etc.)  │
│  - Business logic                                      │
│  - Data processing                                     │
│  - IPFS operations                                     │
└─────────────────────────────────────────────────────────┘
```

### 2.2 Key Design Patterns

**1. ServerContext Pattern (NEW - Week 3)**
```python
# Dependency injection for global resources
context = ServerContext()
context.tool_manager = HierarchicalToolManager(context)
context.metadata_registry = ToolMetadataRegistry(context)

# Backward compatibility with globals
resource = get_resource(context=context)  # Use context
resource = get_resource()  # Fallback to global
```

**2. Protocol Pattern (NEW - Week 4)**
```python
# Eliminate circular dependencies with TYPE_CHECKING
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from .mcp_interfaces import MCPServerProtocol

class MyAdapter:
    def use_server(self, server: "MCPServerProtocol"):
        # Type hints preserved, no circular import
        pass
```

**3. Thin Tool Pattern (Established)**
```python
@mcp.tool()
async def my_tool(param: str) -> str:
    """Thin wrapper delegates to core module."""
    from ipfs_datasets_py.core import do_work
    return await do_work(param)
```

**4. Hierarchical Registration (Week 5)**
```python
# Hierarchical tool discovery eliminates duplicate registration
def _get_hierarchical_tools() -> dict[str, dict[str, Callable]]:
    """Discover tools from HierarchicalToolManager automatically."""
    # Eliminates 377 → 4 registrations (99% reduction)
```

### 2.3 Data Flow

**Request Flow:**
1. Client → MCP Server (server.py or fastapi_service.py)
2. Server validates request and extracts tool name + parameters
3. Tool registry routes to appropriate tool category
4. Tool wrapper validates parameters and calls core module
5. Core module executes business logic
6. Result flows back through layers to client

**P2P Workflow Flow:**
1. Client → MCP Server → P2P Service Manager
2. Task submission via TaskQueueWrapper
3. Workflow scheduler assigns to workers (Docker containers)
4. Worker executes tool via MCP server
5. Results stored in IPFS via ipfs_backend_router
6. Client retrieves CID and fetches result

---

## 3. Critical Issues Breakdown

### 3.1 Code Quality Issues (High Priority)

#### Issue 1: Complex Function - `_get_hierarchical_tools` (114 lines)
**File:** `p2p_mcp_registry_adapter.py:126-240`  
**Severity:** HIGH  
**Impact:** Difficult to maintain, test, understand

**Problem:**
```python
def _get_hierarchical_tools(self) -> dict[str, dict[str, Callable]]:
    """114-line function with 7+ nested try-except blocks."""
    # Line 162: asyncio.run() - event loop issue
    # Line 177: asyncio.run() - event loop issue
    # Lines 194-206: Closure variable capture bug
    # Lines 148-228: Multiple bare except Exception blocks
```

**Solution:**
- Extract into 4 smaller functions (30 lines each):
  - `_discover_categories()` - Find tool categories
  - `_load_category_tools()` - Load tools from category
  - `_create_tool_wrapper()` - Create MCP tool wrapper
  - `_validate_tool()` - Validate tool interface
- Replace `asyncio.run()` with proper async context
- Fix closure variable capture with explicit binding
- Add specific exception types

**Effort:** 4-6 hours  
**Tests:** 15 tests (category discovery, tool loading, wrapper creation, validation)

#### Issue 2: Bare Exception Handlers (10+ instances)
**Files:** Multiple (p2p_mcp_registry_adapter.py, tool files)  
**Severity:** HIGH  
**Impact:** Masks real errors, makes debugging impossible

**Examples:**
```python
# BAD - catches everything including KeyboardInterrupt
try:
    risky_operation()
except Exception as e:
    logger.error(f"Failed: {e}")  # What type of error?
    return None  # Silent failure

# GOOD - specific exception types
try:
    risky_operation()
except (ValueError, KeyError) as e:
    logger.error(f"Invalid input: {e}", exc_info=True)
    raise ToolExecutionError(f"Operation failed: {e}") from e
except ImportError as e:
    logger.warning(f"Optional dependency missing: {e}")
    return {"status": "degraded", "error": str(e)}
```

**Solution:**
- Audit all `except Exception` blocks
- Replace with specific exception types
- Add proper error propagation
- Log with `exc_info=True` for stack traces

**Effort:** 3-4 hours  
**Tests:** 8 tests (error handling, specific exceptions, logging)

#### Issue 3: Type Hint Inconsistencies (30+ instances)
**Files:** Multiple (fastapi_service.py, tool files)  
**Severity:** MEDIUM  
**Impact:** Type checkers fail, IDE autocomplete broken

**Examples:**
```python
# BAD - default None without Optional[]
def my_func(param: str = None) -> str:
    pass

# GOOD - explicit Optional[]
def my_func(param: Optional[str] = None) -> Optional[str]:
    pass

# BAD - Any type without explanation
def process(data: Any) -> Any:
    pass

# GOOD - specific type or TypeVar
T = TypeVar('T')
def process(data: T) -> T:
    pass
```

**Solution:**
- Run mypy strict mode on all files
- Add missing Optional[] annotations
- Replace Any with specific types where possible
- Add type: ignore comments with justification where needed

**Effort:** 2-3 hours  
**Tests:** 5 tests (type checking, mypy validation)

#### Issue 4: Missing Docstrings (120+ public APIs)
**Files:** Multiple (tool_registry.py, many tools)  
**Severity:** MEDIUM  
**Impact:** Poor developer experience, unclear contracts

**Standard Format:**
```python
def load_dataset(source: str, split: Optional[str] = None) -> Dict[str, Any]:
    """
    Load a dataset from HuggingFace or local source.
    
    This function loads a dataset using the datasets library, with support
    for both remote HuggingFace datasets and local file paths.
    
    Args:
        source: HuggingFace dataset ID (e.g., "squad") or local path
        split: Optional split name (e.g., "train", "test"). If None, loads all splits.
    
    Returns:
        Dictionary containing dataset splits and metadata:
        {
            "splits": {"train": Dataset, "test": Dataset},
            "metadata": {"num_rows": 1000, "features": [...]}
        }
    
    Raises:
        ValueError: If source is invalid or dataset not found
        ImportError: If datasets library is not installed
        
    Example:
        >>> data = load_dataset("squad", split="train")
        >>> print(data["metadata"]["num_rows"])
        87599
    """
```

**Solution:**
- Create docstring template based on docs/_example_docstring_format.md
- Document all public functions, classes, methods
- Include Args, Returns, Raises, Examples
- Add type hints for all parameters

**Effort:** 8-10 hours (can be parallelized)  
**Tests:** 0 tests (documentation only)

#### Issue 5: Closure Variable Capture Bug
**File:** `p2p_mcp_registry_adapter.py:194-206`  
**Severity:** HIGH  
**Impact:** All wrappers may reference last category value

**Problem:**
```python
for cat in categories:
    for name, func in tools.items():
        def wrapper(*args, **kwargs):
            # BUG: 'cat' is captured from loop, may reference last value
            return self._execute_tool(cat, name, func, *args, **kwargs)
```

**Solution:**
```python
for cat in categories:
    for name, func in tools.items():
        # Fix: Explicit binding with default argument
        def wrapper(*args, cat=cat, name=name, func=func, **kwargs):
            return self._execute_tool(cat, name, func, *args, **kwargs)
        
        # Better: Use functools.partial
        from functools import partial
        wrapper = partial(self._execute_tool, cat, name, func)
```

**Effort:** 1 hour  
**Tests:** 3 tests (closure capture, multiple categories)

### 3.2 Architecture Issues (Medium Priority)

#### Issue 6: asyncio.run() from Running Event Loop
**File:** `p2p_mcp_registry_adapter.py:162, 177`  
**Severity:** HIGH  
**Impact:** RuntimeError when called from async context

**Problem:**
```python
@property
def tools(self) -> dict:
    """Property that may be accessed from async code."""
    result = asyncio.run(self._async_get_tools())  # ERROR!
    return result
```

**Solution:**
```python
# Option 1: Make property async (requires API change)
async def get_tools(self) -> dict:
    """Async method for getting tools."""
    return await self._async_get_tools()

# Option 2: Use existing event loop
def tools(self) -> dict:
    """Sync property using existing event loop."""
    try:
        loop = asyncio.get_running_loop()
        # Create task in existing loop
        task = loop.create_task(self._async_get_tools())
        # For properties, we need sync result - cache it
        if not hasattr(self, '_tools_cache'):
            self._tools_cache = None
        return self._tools_cache or {}
    except RuntimeError:
        # No event loop running, safe to create one
        return asyncio.run(self._async_get_tools())

# Option 3: Cache result on initialization
def __init__(self):
    self._tools_cache = asyncio.run(self._async_get_tools())
    
@property
def tools(self) -> dict:
    return self._tools_cache
```

**Effort:** 2-3 hours  
**Tests:** 5 tests (async context, sync context, caching)

#### Issue 7: Missing Input Validation on API Endpoints
**File:** `fastapi_service.py:385-410`  
**Severity:** MEDIUM  
**Impact:** Potential DoS, resource exhaustion

**Problem:**
```python
@app.post("/embeddings/generate")
async def generate_embeddings_api(request: EmbeddingRequest):
    # No validation on batch_size - could be 1000000!
    batch_size = request.batch_size or 32
    # No validation on texts length
    embeddings = await generate_embeddings(request.texts, batch_size=batch_size)
```

**Solution:**
```python
from pydantic import BaseModel, Field, validator

class EmbeddingRequest(BaseModel):
    texts: List[str] = Field(..., max_items=1000)
    batch_size: Optional[int] = Field(default=32, ge=1, le=256)
    model: Optional[str] = Field(default="all-MiniLM-L6-v2")
    
    @validator('texts')
    def validate_texts(cls, v):
        if not v:
            raise ValueError("texts cannot be empty")
        if any(len(text) > 10000 for text in v):
            raise ValueError("Individual text length cannot exceed 10000 characters")
        return v

@app.post("/embeddings/generate")
async def generate_embeddings_api(request: EmbeddingRequest):
    # Pydantic validates automatically
    embeddings = await generate_embeddings(
        request.texts, 
        batch_size=request.batch_size,
        model=request.model
    )
```

**Effort:** 2-3 hours  
**Tests:** 8 tests (validation, limits, error cases)

### 3.3 Testing Gaps (High Priority)

#### Gap 1: server.py Core Functionality (0% coverage)
**File:** `server.py` (926 lines)  
**Coverage:** 0%  
**Target:** 40-50 tests, 75%+ coverage

**Test Categories:**
1. **Tool Registration (10 tests)**
   - Register single tool
   - Register category of tools
   - Duplicate registration handling
   - Invalid tool schemas
   - Tool metadata propagation

2. **Tool Execution (10 tests)**
   - Successful tool execution
   - Tool parameter validation
   - Tool error handling
   - Async tool execution
   - Tool timeout handling

3. **P2P Integration (8 tests)**
   - P2P service initialization
   - Workflow scheduler integration
   - Task queue integration
   - Peer registry integration
   - Graceful degradation when P2P unavailable

4. **Configuration (8 tests)**
   - YAML config loading
   - Environment variable overrides
   - CLI argument parsing
   - Config validation
   - Default values

5. **Error Handling (8 tests)**
   - Import errors
   - Tool execution errors
   - Invalid requests
   - Timeout handling
   - Resource cleanup

**Effort:** 12-15 hours  
**Files:** `tests/mcp/test_server_core.py` (1,200+ lines)

#### Gap 2: hierarchical_tool_manager.py (0% coverage)
**File:** `hierarchical_tool_manager.py` (536 lines)  
**Coverage:** 0%  
**Target:** 20-25 tests, 75%+ coverage

**Test Categories:**
1. **Tool Discovery (8 tests)**
   - Category discovery
   - Tool loading from category
   - Hierarchical structure validation
   - Dynamic loading
   - Cache invalidation

2. **Tool Access (7 tests)**
   - Get tool by flat name
   - Get tool by hierarchical name (category/operation)
   - List all tools
   - List tools by category
   - Tool metadata retrieval

3. **ServerContext Integration (5 tests)**
   - Context initialization
   - Context-aware tool loading
   - Fallback to global
   - Thread safety
   - Context cleanup

**Effort:** 6-8 hours  
**Files:** `tests/mcp/test_hierarchical_tool_manager.py` (600+ lines)

#### Gap 3: fastapi_config.py & fastapi_service.py (5% coverage)
**Files:** `fastapi_config.py`, `fastapi_service.py` (1,152 lines)  
**Coverage:** 5%  
**Target:** 10-15 tests, 70%+ coverage

**Test Categories:**
1. **Configuration (5 tests)**
   - Config loading from YAML
   - Environment variable overrides
   - Validation
   - Default values
   - Secret key enforcement

2. **API Endpoints (10 tests)**
   - Health check endpoint
   - Tool listing endpoint
   - Tool execution endpoint
   - Embedding generation endpoint
   - Error responses
   - Authentication/authorization

**Effort:** 4-5 hours  
**Files:** `tests/mcp/test_fastapi.py` (400+ lines)

---

## 4. Phase 2 Completion Plan (Weeks 6-7)

### 4.1 Week 6: Thick Tool Refactoring (8-12 hours)

**Objective:** Extract business logic from 3 thick tools into reusable core libraries

#### Tool 1: enhanced_ipfs_cluster_tools.py (800+ lines → ~150 lines)

**Current Issues:**
- Embedded cluster management logic (400+ lines)
- Direct IPFS HTTP API calls (200+ lines)
- Configuration parsing (100+ lines)
- Duplicate code with ipfs_tools

**Refactoring Plan:**
1. **Create core module:** `ipfs_datasets_py/ipfs_cluster/cluster_manager.py`
   - Extract cluster operations (add, pin, status, peers)
   - Reusable by CLI, MCP, and third-party code
   - ~500 lines
   
2. **Create thin wrapper:** `enhanced_ipfs_cluster_tools.py` (150 lines)
   ```python
   @mcp.tool()
   async def cluster_add(cid: str, replication_factor: int = 3) -> Dict:
       """Add content to IPFS cluster with replication."""
       from ipfs_datasets_py.ipfs_cluster import ClusterManager
       manager = ClusterManager()
       return await manager.add(cid, replication_factor)
   ```

3. **Tests:**
   - Core module tests: 20 tests (cluster_manager)
   - Tool wrapper tests: 8 tests (thin wrapper)
   - Integration tests: 5 tests (E2E)

**Effort:** 3-4 hours  
**LOC:** +500 (core), -650 (tool), net -150  
**Tests:** 33 tests

#### Tool 2: geospatial_analysis_tools.py (600+ lines → ~120 lines)

**Current Issues:**
- Embedded geospatial calculation logic (350+ lines)
- Coordinate transformation logic (150+ lines)
- Visualization generation (100+ lines)

**Refactoring Plan:**
1. **Create core module:** `ipfs_datasets_py/geospatial/analyzer.py`
   - Extract geospatial operations (distance, area, intersections)
   - Extract coordinate transformations
   - Reusable by CLI, notebooks, MCP
   - ~400 lines

2. **Create thin wrapper:** `geospatial_analysis_tools.py` (120 lines)
   ```python
   @mcp.tool()
   async def calculate_distance(point1: Tuple[float, float], 
                                 point2: Tuple[float, float],
                                 method: str = "haversine") -> float:
       """Calculate distance between two geographic points."""
       from ipfs_datasets_py.geospatial import GeospatialAnalyzer
       analyzer = GeospatialAnalyzer()
       return analyzer.calculate_distance(point1, point2, method)
   ```

3. **Tests:**
   - Core module tests: 25 tests (analyzer)
   - Tool wrapper tests: 7 tests (thin wrapper)
   - Integration tests: 3 tests (E2E)

**Effort:** 3-4 hours  
**LOC:** +400 (core), -480 (tool), net -80  
**Tests:** 35 tests

#### Tool 3: web_archive/common_crawl_tools.py (500+ lines → ~100 lines)

**Current Issues:**
- Embedded Common Crawl API logic (300+ lines)
- WARC file parsing (150+ lines)
- Index querying (50+ lines)

**Refactoring Plan:**
1. **Create core module:** `ipfs_datasets_py/web_archive/common_crawl.py`
   - Extract Common Crawl operations
   - WARC parsing utilities
   - Index API client
   - ~350 lines

2. **Create thin wrapper:** `common_crawl_tools.py` (100 lines)
   ```python
   @mcp.tool()
   async def search_common_crawl(query: str, 
                                  index: str = "latest",
                                  limit: int = 100) -> List[Dict]:
       """Search Common Crawl index for URLs matching query."""
       from ipfs_datasets_py.web_archive import CommonCrawlClient
       client = CommonCrawlClient()
       return await client.search(query, index, limit)
   ```

3. **Tests:**
   - Core module tests: 20 tests (common_crawl)
   - Tool wrapper tests: 6 tests (thin wrapper)
   - Integration tests: 4 tests (E2E)

**Effort:** 2-4 hours  
**LOC:** +350 (core), -400 (tool), net -50  
**Tests:** 30 tests

#### Week 6 Summary

**Total Effort:** 8-12 hours  
**Total LOC Change:** +1,250 (core), -1,530 (tools), net -280  
**Total Tests:** 98 new tests  
**Tool Compliance:** 88% → 95% (target achieved)

**Deliverables:**
1. 3 new core modules (cluster_manager, analyzer, common_crawl)
2. 3 refactored thin tools (150, 120, 100 lines)
3. 98 comprehensive tests
4. Updated documentation

### 4.2 Week 7: Phase 3 Core Testing (Start) (20-25 hours)

**Objective:** Begin Phase 3 testing infrastructure with server.py coverage

#### Component 1: server.py Testing (40-50 tests, 12-15 hours)

**Test Suite Structure:**
```
tests/mcp/test_server_core.py (1,200+ lines)
├── TestToolRegistration (10 tests)
├── TestToolExecution (10 tests)
├── TestP2PIntegration (8 tests)
├── TestConfiguration (8 tests)
├── TestErrorHandling (8 tests)
└── TestCleanup (6 tests)
```

**Key Test Scenarios:**

1. **Tool Registration:**
   ```python
   def test_register_single_tool():
       """Test registering a single MCP tool."""
       server = MCPServer()
       
       @mcp.tool()
       def my_tool(x: int) -> int:
           return x * 2
       
       server.register_tool(my_tool)
       assert "my_tool" in server.list_tools()
       result = server.execute_tool("my_tool", {"x": 5})
       assert result == 10
   ```

2. **P2P Integration:**
   ```python
   @pytest.mark.asyncio
   async def test_p2p_workflow_submission():
       """Test submitting workflow to P2P task queue."""
       server = MCPServer(enable_p2p=True)
       
       workflow = {"task": "process_dataset", "params": {...}}
       task_id = await server.submit_workflow(workflow)
       
       assert task_id is not None
       status = await server.get_task_status(task_id)
       assert status["state"] in ["pending", "running", "completed"]
   ```

3. **Error Handling:**
   ```python
   def test_tool_execution_timeout():
       """Test tool execution with timeout."""
       server = MCPServer(tool_timeout=1.0)
       
       @mcp.tool()
       async def slow_tool():
           await asyncio.sleep(5)
           return "done"
       
       server.register_tool(slow_tool)
       
       with pytest.raises(TimeoutError):
           server.execute_tool("slow_tool", {})
   ```

**Effort:** 12-15 hours  
**Tests:** 40-50 tests  
**Coverage:** 75%+ of server.py

#### Component 2: hierarchical_tool_manager.py Testing (20-25 tests, 6-8 hours)

**Test Suite Structure:**
```
tests/mcp/test_hierarchical_tool_manager.py (600+ lines)
├── TestToolDiscovery (8 tests)
├── TestToolAccess (7 tests)
└── TestServerContextIntegration (5-10 tests)
```

**Effort:** 6-8 hours  
**Tests:** 20-25 tests  
**Coverage:** 75%+ of hierarchical_tool_manager.py

#### Week 7 Summary

**Total Effort:** 18-23 hours (within 20-25 hour budget)  
**Total Tests:** 60-75 new tests  
**Coverage:** server.py (75%+), hierarchical_tool_manager.py (75%+)  
**Overall MCP Coverage:** 18% → 35-40%

---

## 5. Phase 3 Testing Strategy (Weeks 7-10)

### 5.1 Testing Goals

**Objectives:**
1. Achieve 75%+ test coverage on core MCP server modules
2. Create 170-210 comprehensive tests
3. Validate all critical paths and error cases
4. Establish testing infrastructure for future development

**Coverage Targets:**
- Core server modules: 75%+ (server.py, hierarchical_tool_manager.py)
- P2P integration: 70%+ (p2p_mcp_registry_adapter.py, p2p_service_manager.py)
- FastAPI layer: 70%+ (fastapi_service.py, fastapi_config.py)
- Tool wrappers: 60%+ (sample 10-15 tools)
- Overall MCP server: 60%+

### 5.2 Test Infrastructure

#### Test Categories

1. **Unit Tests (80-100 tests)**
   - Individual function testing
   - Mocked dependencies
   - Edge cases and error conditions
   - Fast execution (<0.1s per test)

2. **Integration Tests (50-70 tests)**
   - Component interaction
   - Real dependencies (where feasible)
   - End-to-end workflows
   - Medium execution (<1s per test)

3. **P2P Integration Tests (20-30 tests)**
   - P2P service interaction
   - Workflow submission and execution
   - IPFS storage and retrieval
   - TaskQueue operations

4. **Performance Tests (10-15 tests)**
   - Tool execution latency
   - Memory usage
   - Concurrent request handling
   - Resource cleanup

5. **Regression Tests (10 tests)**
   - Security fixes (Phase 1)
   - Architecture improvements (Phase 2)
   - Bug fixes

#### Test Fixtures

```python
# tests/mcp/conftest.py

@pytest.fixture
def mcp_server():
    """Create a test MCP server instance."""
    from ipfs_datasets_py.mcp_server import server
    srv = server.create_server(config={"test_mode": True})
    yield srv
    srv.cleanup()

@pytest.fixture
def server_context():
    """Create a test ServerContext."""
    from ipfs_datasets_py.mcp_server.server_context import ServerContext
    ctx = ServerContext()
    yield ctx
    ctx.cleanup()

@pytest.fixture
def mock_ipfs():
    """Mock IPFS client for testing."""
    with patch('ipfs_datasets_py.mcp_server.ipfs_client') as mock:
        mock.add_bytes.return_value = "QmTest123..."
        mock.cat.return_value = b"test data"
        yield mock

@pytest.fixture
async def async_server():
    """Create async test server."""
    server = await create_async_server()
    yield server
    await server.cleanup()
```

### 5.3 Testing Timeline (Weeks 7-10)

#### Week 7: Core Server Testing (Start)
- ✅ server.py testing (40-50 tests, 12-15 hours)
- ✅ hierarchical_tool_manager.py testing (20-25 tests, 6-8 hours)
- **Total:** 60-75 tests, 18-23 hours

#### Week 8: P2P and Configuration Testing
- p2p_mcp_registry_adapter.py (15-20 tests, 5-6 hours)
- p2p_service_manager.py (10-15 tests, 3-4 hours)
- fastapi_config.py (5-8 tests, 2-3 hours)
- **Total:** 30-43 tests, 10-13 hours

#### Week 9: FastAPI and Tool Testing
- fastapi_service.py endpoints (10-15 tests, 4-5 hours)
- Sample tool testing (20-25 tests, 6-8 hours)
- Performance tests (10-15 tests, 4-5 hours)
- **Total:** 40-55 tests, 14-18 hours

#### Week 10: Integration and Validation
- P2P integration tests (15-20 tests, 6-8 hours)
- End-to-end workflows (10-15 tests, 4-6 hours)
- Regression testing (10 tests, 2-3 hours)
- Documentation and cleanup (4-5 hours)
- **Total:** 35-45 tests, 16-22 hours

**Phase 3 Total:**
- **Tests:** 165-218 new tests (target: 170-210 ✅)
- **Effort:** 58-76 hours
- **Coverage:** 60%+ overall, 75%+ core modules
- **Duration:** 4 weeks (15-20 hours/week)

---

## 6. Code Quality Improvement Roadmap

### 6.1 Code Quality Metrics

**Current State:**
- Complex functions (>100 lines): 8
- Bare exceptions: 10+
- Missing docstrings: 120+
- Type hint issues: 30+
- TODOs in production: 15+

**Target State:**
- Complex functions: 0
- Bare exceptions: 0
- Missing docstrings: 0
- Type hint issues: 0
- TODOs documented/tracked: 100%

### 6.2 Code Quality Phases

#### Phase A: Critical Function Refactoring (6-8 hours)

**Targets:**
1. `p2p_mcp_registry_adapter._get_hierarchical_tools` (114 lines → 4 functions × 30 lines)
2. `fastapi_service.generate_embeddings_api` (48 lines → refactor validation)
3. `server._initialize_p2p_services` (60+ lines → extract helpers)

**Process:**
1. Identify complex function
2. Extract logical blocks into helper functions
3. Add comprehensive docstrings
4. Add type hints
5. Write unit tests for each helper
6. Validate cyclomatic complexity <10

**Deliverables:**
- Refactored functions with <50 lines each
- Helper functions with clear responsibilities
- 30-40 new unit tests
- Docstrings for all functions

#### Phase B: Exception Handling Standardization (4-5 hours)

**Process:**
1. Audit all `except Exception` blocks
2. Categorize exceptions by domain:
   - I/O errors (IOError, FileNotFoundError)
   - Network errors (requests.RequestException, httpx.HTTPError)
   - Validation errors (ValueError, ValidationError)
   - Import errors (ImportError, ModuleNotFoundError)
3. Replace with specific exception types
4. Add proper error logging with `exc_info=True`
5. Document exception handling strategy

**Deliverables:**
- Exception handling guide
- Standardized error patterns
- Updated all catch blocks
- 15-20 error handling tests

#### Phase C: Type Hint Completion (4-6 hours)

**Process:**
1. Run mypy in strict mode: `mypy ipfs_datasets_py/mcp_server --strict`
2. Fix all type errors
3. Add missing Optional[] annotations
4. Replace Any with specific types or TypeVar
5. Add type: ignore with justification where needed
6. Validate with mypy and pyright

**Tools:**
- mypy (strict mode)
- pyright (type checking)
- MonkeyType (runtime type collection)

**Deliverables:**
- 100% type hint coverage
- mypy strict mode passing
- Type checking CI integration

#### Phase D: Documentation Completion (8-12 hours)

**Process:**
1. Audit all public APIs (functions, classes, methods)
2. Create docstring checklist
3. Apply standard format from docs/_example_docstring_format.md
4. Include Args, Returns, Raises, Examples
5. Generate API documentation with Sphinx

**Deliverables:**
- Docstrings for all 120+ public APIs
- Generated API documentation (HTML)
- Examples for common use cases
- Migration guides

### 6.3 Quality Assurance

#### Code Quality Checks (CI Integration)

```yaml
# .github/workflows/code-quality.yml
name: Code Quality

on: [push, pull_request]

jobs:
  quality:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      
      - name: Type Checking
        run: |
          mypy ipfs_datasets_py/mcp_server --strict
          pyright ipfs_datasets_py/mcp_server
      
      - name: Linting
        run: |
          flake8 ipfs_datasets_py/mcp_server
          pylint ipfs_datasets_py/mcp_server
      
      - name: Complexity Check
        run: |
          radon cc ipfs_datasets_py/mcp_server -a -nb
          # Fail if any function has complexity > 10
      
      - name: Documentation Check
        run: |
          pydocstyle ipfs_datasets_py/mcp_server
          interrogate ipfs_datasets_py/mcp_server --fail-under 90
      
      - name: Security Scan
        run: |
          bandit -r ipfs_datasets_py/mcp_server
          safety check
```

**Quality Metrics:**
- Cyclomatic complexity: <10 per function
- Docstring coverage: >90%
- Type hint coverage: 100%
- Security issues: 0
- Test coverage: >75%

---

## 7. Performance Optimization Plan

### 7.1 Performance Bottlenecks

**Identified Issues:**
1. Tool registration overhead (FIXED - Week 5: 377→4 registrations, 99% reduction)
2. Blocking operations in startup (2.0s timeout in P2P initialization)
3. Synchronous tool execution (no parallelism)
4. IPFS operations latency (~200ms per operation)
5. No caching for repeated tool calls
6. Inefficient tool discovery (linear search)

### 7.2 Optimization Phases

#### Phase 1: Startup Optimization (2-3 hours)

**Target:** Reduce server startup time from 3-5s to <1s

**Optimizations:**
1. Lazy tool loading (load on first use, not at startup)
2. Parallel tool discovery (use asyncio.gather)
3. Cache tool metadata (avoid repeated file system scans)
4. Defer P2P initialization to first P2P call

**Implementation:**
```python
class HierarchicalToolManager:
    def __init__(self):
        self._tool_cache = {}  # Lazy cache
        self._discovery_done = False
    
    def get_tool(self, name: str) -> Callable:
        """Get tool with lazy loading."""
        if name not in self._tool_cache:
            self._load_tool(name)  # Load on demand
        return self._tool_cache[name]
    
    async def discover_tools_async(self):
        """Parallel tool discovery."""
        categories = await asyncio.gather(
            *[self._discover_category(cat) for cat in self._get_categories()]
        )
```

**Expected Improvement:** 60-70% startup time reduction

#### Phase 2: Tool Execution Optimization (3-4 hours)

**Target:** Enable parallel tool execution for independent operations

**Optimizations:**
1. Add async execution pool
2. Batch similar operations
3. Enable parallel tool execution with asyncio
4. Add execution timeout per tool

**Implementation:**
```python
class MCPServer:
    async def execute_tools_parallel(self, calls: List[ToolCall]) -> List[Result]:
        """Execute multiple independent tools in parallel."""
        tasks = [
            asyncio.create_task(self.execute_tool(call.name, call.params))
            for call in calls
        ]
        return await asyncio.gather(*tasks, return_exceptions=True)
```

**Expected Improvement:** 3-5x throughput for parallel requests

#### Phase 3: IPFS Caching (4-5 hours)

**Target:** Reduce IPFS operation latency from ~200ms to <50ms (75% reduction)

**Optimizations:**
1. Add LRU cache for IPFS operations
2. Prefetch common CIDs
3. Local pin cache
4. Batch IPFS operations

**Implementation:**
```python
from functools import lru_cache

class IPFSCache:
    def __init__(self, max_size: int = 1000):
        self._cache = LRUCache(max_size)
    
    @lru_cache(maxsize=1000)
    async def cat(self, cid: str) -> bytes:
        """Get content with caching."""
        if cid in self._cache:
            return self._cache[cid]
        
        content = await ipfs_client.cat(cid)
        self._cache[cid] = content
        return content
```

**Expected Improvement:** 75% latency reduction for cached content

#### Phase 4: Query Optimization (2-3 hours)

**Target:** Optimize tool discovery and metadata queries

**Optimizations:**
1. Index tools by category (O(1) lookup)
2. Cache tool schemas
3. Use binary search for sorted tool lists
4. Precompute tool capabilities

**Implementation:**
```python
class ToolRegistry:
    def __init__(self):
        self._tool_index = {}  # category -> tools
        self._schema_cache = {}  # tool_name -> schema
    
    def find_tools_by_category(self, category: str) -> List[Tool]:
        """O(1) lookup by category."""
        return self._tool_index.get(category, [])
```

**Expected Improvement:** 90% reduction in query time

### 7.3 Performance Testing

**Benchmarks:**
```python
# tests/mcp/benchmarks/test_performance.py

import pytest
import time

def test_server_startup_time():
    """Server startup should be <1s."""
    start = time.time()
    server = MCPServer()
    elapsed = time.time() - start
    assert elapsed < 1.0, f"Startup took {elapsed:.2f}s"

@pytest.mark.asyncio
async def test_parallel_tool_execution():
    """Parallel execution should be 3x faster than sequential."""
    server = MCPServer()
    
    # Sequential
    start = time.time()
    for i in range(10):
        await server.execute_tool("test_tool", {"x": i})
    sequential_time = time.time() - start
    
    # Parallel
    start = time.time()
    await server.execute_tools_parallel([
        ToolCall("test_tool", {"x": i}) for i in range(10)
    ])
    parallel_time = time.time() - start
    
    speedup = sequential_time / parallel_time
    assert speedup > 3.0, f"Speedup only {speedup:.1f}x"

def test_ipfs_cache_hit_rate():
    """IPFS cache hit rate should be >80%."""
    cache = IPFSCache()
    
    # Prime cache
    for cid in test_cids[:100]:
        cache.cat(cid)
    
    # Test hit rate
    hits = sum(1 for cid in test_cids[:100] if cache.cat(cid))
    hit_rate = hits / 100
    assert hit_rate > 0.8, f"Hit rate only {hit_rate:.0%}"
```

**Performance Targets:**
- Server startup: <1s
- Tool execution: <10ms overhead
- IPFS operations: <50ms with caching
- Parallel throughput: 3-5x improvement
- Memory usage: <500MB baseline

---

## 8. Documentation Strategy

### 8.1 Documentation Structure

**Current Documentation (190KB+, 10 docs):**
- COMPREHENSIVE_REFACTORING_PLAN_2026.md (45KB)
- PHASE_2_COMPLETION_AND_WEEK_6_7_ROADMAP.md (45KB)
- MCP_MCPLUSPLUS_IMPROVEMENT_PLAN.md (54KB)
- SECURITY.md (security guide)
- README.md (overview)
- Various phase completion docs

**Target Documentation Structure:**
```
docs/
├── guides/
│   ├── getting-started.md
│   ├── tool-development.md
│   ├── p2p-integration.md
│   └── deployment.md
├── api/
│   ├── server.md
│   ├── hierarchical-tool-manager.md
│   ├── tool-registry.md
│   └── p2p-services.md
├── architecture/
│   ├── overview.md
│   ├── thin-tool-pattern.md
│   ├── servercontext-pattern.md
│   └── p2p-architecture.md
├── development/
│   ├── testing.md
│   ├── code-quality.md
│   ├── tool-templates/
│   └── contributing.md
└── history/
    ├── phase-1-security.md
    ├── phase-2-architecture.md
    └── phase-3-testing.md
```

### 8.2 Documentation Priorities

#### Priority 1: Developer Onboarding (4-6 hours)

**Documents:**
1. **Getting Started Guide** (guides/getting-started.md)
   - Installation
   - Quick start examples
   - Basic tool usage
   - Common patterns

2. **Tool Development Guide** (guides/tool-development.md)
   - ClaudeMCPTool pattern
   - Thin tool best practices
   - Testing tools
   - Publishing tools

3. **API Reference** (api/)
   - Auto-generated from docstrings
   - Interactive examples
   - Type information
   - Error handling

#### Priority 2: Architecture Documentation (3-4 hours)

**Documents:**
1. **Architecture Overview** (architecture/overview.md)
   - Layered architecture diagram
   - Component responsibilities
   - Data flow
   - Design patterns

2. **Pattern Guides** (architecture/)
   - Thin Tool Pattern
   - ServerContext Pattern
   - Protocol Pattern
   - Hierarchical Organization

#### Priority 3: Maintenance Documentation (2-3 hours)

**Documents:**
1. **Testing Guide** (development/testing.md)
   - Test structure
   - Fixtures
   - CI integration
   - Performance testing

2. **Code Quality Guide** (development/code-quality.md)
   - Style guidelines
   - Type hints
   - Docstrings
   - CI checks

### 8.3 Documentation Automation

**Auto-generated Documentation:**
```bash
# Generate API docs from docstrings
sphinx-apidoc -o docs/api ipfs_datasets_py/mcp_server

# Generate coverage reports
pytest --cov=ipfs_datasets_py/mcp_server --cov-report=html

# Generate complexity reports
radon cc ipfs_datasets_py/mcp_server -a --json > docs/complexity.json

# Generate dependency graphs
pydeps ipfs_datasets_py/mcp_server --max-bacon=2 > docs/dependencies.svg
```

**Documentation CI:**
```yaml
# .github/workflows/docs.yml
name: Documentation

on:
  push:
    branches: [main]
    paths:
      - 'ipfs_datasets_py/mcp_server/**'
      - 'docs/**'

jobs:
  build-docs:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      
      - name: Build API Docs
        run: sphinx-build -b html docs docs/_build
      
      - name: Deploy to GitHub Pages
        uses: peaceiris/actions-gh-pages@v3
        with:
          github_token: ${{ secrets.GITHUB_TOKEN }}
          publish_dir: docs/_build
```

---

## 9. Testing Infrastructure

### 9.1 Test Organization

**Test Directory Structure:**
```
tests/mcp/
├── conftest.py (fixtures)
├── test_server_core.py (40-50 tests)
├── test_hierarchical_tool_manager.py (20-25 tests)
├── test_p2p_integration.py (20-30 tests)
├── test_fastapi.py (15-20 tests)
├── test_tool_wrappers.py (20-25 tests)
├── test_performance.py (10-15 tests)
├── test_error_handling.py (15-20 tests)
└── benchmarks/
    ├── test_startup_time.py
    ├── test_tool_execution.py
    └── test_ipfs_operations.py
```

### 9.2 Testing Patterns

#### Pattern 1: Unit Test with Mocking
```python
@pytest.fixture
def mock_ipfs():
    """Mock IPFS client."""
    with patch('ipfs_datasets_py.mcp_server.ipfs_client') as mock:
        mock.add_bytes.return_value = "QmTest..."
        mock.cat.return_value = b"test data"
        yield mock

def test_tool_with_mocked_ipfs(mock_ipfs):
    """Test tool with mocked IPFS operations."""
    result = execute_tool("ipfs_add", {"content": "test"})
    assert result["cid"] == "QmTest..."
    mock_ipfs.add_bytes.assert_called_once()
```

#### Pattern 2: Integration Test with Real Dependencies
```python
@pytest.mark.integration
@pytest.mark.asyncio
async def test_end_to_end_workflow():
    """Test complete workflow with real components."""
    server = await create_server(test_mode=False)
    
    # Submit workflow
    workflow_id = await server.submit_workflow({
        "task": "process_dataset",
        "params": {"source": "squad"}
    })
    
    # Wait for completion
    result = await server.wait_for_workflow(workflow_id, timeout=30)
    assert result["status"] == "completed"
```

#### Pattern 3: Property-Based Testing
```python
from hypothesis import given, strategies as st

@given(st.text(min_size=1, max_size=1000))
def test_tool_handles_arbitrary_input(input_text):
    """Tool should handle any valid string input."""
    result = execute_tool("process_text", {"text": input_text})
    assert "error" not in result
    assert len(result["output"]) >= 0
```

### 9.3 Test Automation

**Continuous Integration:**
```yaml
# .github/workflows/tests.yml
name: Tests

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python-version: [3.10, 3.11, 3.12]
    
    steps:
      - uses: actions/checkout@v3
      
      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: ${{ matrix.python-version }}
      
      - name: Install dependencies
        run: |
          pip install -e ".[test]"
      
      - name: Run unit tests
        run: pytest tests/mcp -v -m "not integration"
      
      - name: Run integration tests
        run: pytest tests/mcp -v -m integration
      
      - name: Generate coverage report
        run: |
          pytest --cov=ipfs_datasets_py/mcp_server \
                 --cov-report=xml \
                 --cov-report=html
      
      - name: Upload coverage
        uses: codecov/codecov-action@v3
```

**Test Markers:**
```python
# pytest.ini
[pytest]
markers =
    unit: Unit tests (fast, isolated)
    integration: Integration tests (real dependencies)
    slow: Slow tests (>1s execution time)
    p2p: Tests requiring P2P infrastructure
    performance: Performance benchmarks
```

---

## 10. Success Metrics & KPIs

### 10.1 Code Quality Metrics

| Metric | Baseline | Phase 2 Target | Phase 3 Target | Current |
|--------|----------|----------------|----------------|---------|
| **Test Coverage** | 18% | 35-40% | 75%+ | TBD |
| **Complex Functions (>100 lines)** | 8 | 3 | 0 | TBD |
| **Bare Exception Handlers** | 10+ | 0 | 0 | TBD |
| **Missing Docstrings** | 120+ | 30 | 0 | TBD |
| **Type Hint Coverage** | 70% | 90% | 100% | TBD |
| **Cyclomatic Complexity (avg)** | 6.2 | 5.0 | 4.0 | TBD |
| **Security Issues** | 0 | 0 | 0 | ✅ 0 |
| **Code Smells** | 50+ | 15-20 | <5 | TBD |

### 10.2 Performance Metrics

| Metric | Baseline | Target | Current |
|--------|----------|--------|---------|
| **Server Startup Time** | 3-5s | <1s | TBD |
| **Tool Execution Overhead** | ~50ms | <10ms | TBD |
| **IPFS Operation Latency** | ~200ms | <50ms | TBD |
| **Tool Registration Overhead** | 377 calls | 4 calls | ✅ 4 |
| **Parallel Throughput** | 1x | 3-5x | TBD |
| **Memory Usage (baseline)** | 800MB | <500MB | TBD |
| **Cache Hit Rate** | N/A | >80% | TBD |

### 10.3 Architecture Metrics

| Metric | Baseline | Target | Current |
|--------|----------|--------|---------|
| **Global Singletons** | 30+ | <5 | ✅ 26 |
| **Circular Dependencies** | 2+ | 0 | ✅ 0 |
| **Thin Tools (<150 lines)** | 85% | 95% | TBD |
| **Tool Categories** | 50 | 50 | ✅ 50 |
| **Total Tools** | 321 | 321 | ✅ 321 |
| **Documentation Coverage** | 40% | 90%+ | TBD |

### 10.4 Testing Metrics

| Metric | Baseline | Phase 2 Target | Phase 3 Target | Current |
|--------|----------|----------------|----------------|---------|
| **Total Tests** | 64 | 162-172 | 234-282 | ✅ 64 |
| **Unit Tests** | 40 | 80-100 | 140-170 | TBD |
| **Integration Tests** | 20 | 50-70 | 70-90 | TBD |
| **P2P Tests** | 4 | 12-14 | 24-34 | TBD |
| **Performance Tests** | 0 | 10-15 | 10-15 | TBD |
| **Test Execution Time** | ~2s | ~10s | ~20s | TBD |
| **Test Pass Rate** | 100% | 100% | 100% | ✅ 100% |

### 10.5 Milestone Tracking

#### Phase 2 Week 6 Milestones
- [ ] Refactor 3 thick tools to thin wrappers
- [ ] Extract 1,250 LOC to core modules
- [ ] Reduce tool LOC by 280 lines (net)
- [ ] Add 98 new tests
- [ ] Achieve 88% → 95% thin tool compliance

#### Phase 2 Week 7 Milestones
- [ ] Add 60-75 new tests (server.py, hierarchical_tool_manager.py)
- [ ] Achieve 75%+ coverage on server.py
- [ ] Achieve 75%+ coverage on hierarchical_tool_manager.py
- [ ] Reach 35-40% overall MCP coverage

#### Phase 3 Completion Milestones
- [ ] Add 170-210 total new tests
- [ ] Achieve 75%+ overall test coverage
- [ ] Zero complex functions (>100 lines)
- [ ] Zero bare exception handlers
- [ ] 100% type hint coverage
- [ ] 90%+ documentation coverage

---

## 11. Risk Management

### 11.1 Technical Risks

#### Risk 1: Breaking Changes in Refactoring
**Probability:** Medium  
**Impact:** High  
**Mitigation:**
- Maintain backward compatibility at all times
- Use deprecation warnings before removing old APIs
- Comprehensive regression testing
- Feature flags for new functionality

#### Risk 2: Performance Regression
**Probability:** Low  
**Impact:** Medium  
**Mitigation:**
- Continuous performance monitoring
- Benchmark tests in CI
- Profile before and after changes
- Rollback plan for performance issues

#### Risk 3: Test Coverage Gaps
**Probability:** Medium  
**Impact:** Medium  
**Mitigation:**
- Prioritize high-risk areas (server.py, P2P layer)
- Code review for new code without tests
- Coverage reports in CI
- Gradually increase coverage targets

#### Risk 4: Documentation Drift
**Probability:** High  
**Impact:** Low  
**Mitigation:**
- Auto-generate API docs from docstrings
- Documentation CI checks
- Regular documentation reviews
- Keep docs close to code

### 11.2 Resource Risks

#### Risk 5: Timeline Slippage
**Probability:** Medium  
**Impact:** Low  
**Mitigation:**
- Conservative time estimates (buffer 20-30%)
- Prioritize critical work
- Parallel work streams where possible
- Regular progress tracking

#### Risk 6: Scope Creep
**Probability:** High  
**Impact:** Medium  
**Mitigation:**
- Clear phase boundaries
- Documented scope for each phase
- Regular scope reviews
- Defer non-critical work to future phases

### 11.3 Integration Risks

#### Risk 7: P2P Integration Issues
**Probability:** Medium  
**Impact:** Medium  
**Mitigation:**
- Graceful degradation when P2P unavailable
- Comprehensive P2P integration tests
- Mock P2P services for testing
- Fallback to local execution

#### Risk 8: Third-Party Dependencies
**Probability:** Low  
**Impact:** High  
**Mitigation:**
- Pin dependency versions
- Regular security updates
- Vendor critical dependencies
- Fallback implementations

---

## 12. Implementation Timeline

### 12.1 Overview

**Total Duration:** 8-10 weeks (60-80 hours)  
**Intensity:** 15-20 hours/week  
**Team:** 1-2 developers

### 12.2 Detailed Timeline

#### Week 6: Thick Tool Refactoring (8-12 hours)
**Dates:** 2026-02-19 to 2026-02-26

- [ ] Day 1-2: enhanced_ipfs_cluster_tools refactoring (3-4h)
  - Extract ClusterManager to core module (500 lines)
  - Create thin wrapper (150 lines)
  - Add 33 tests
  
- [ ] Day 3-4: geospatial_analysis_tools refactoring (3-4h)
  - Extract GeospatialAnalyzer to core module (400 lines)
  - Create thin wrapper (120 lines)
  - Add 35 tests
  
- [ ] Day 5-6: common_crawl_tools refactoring (2-4h)
  - Extract CommonCrawlClient to core module (350 lines)
  - Create thin wrapper (100 lines)
  - Add 30 tests
  
- [ ] Day 7: Testing and documentation (2h)
  - Integration testing
  - Update documentation
  - Code review

**Deliverables:**
- 3 new core modules (+1,250 LOC)
- 3 refactored thin tools (-1,530 LOC)
- 98 new tests
- Updated documentation

**Status Gate:** Week 6 complete when:
- ✅ All 3 tools refactored to <150 lines
- ✅ 98 tests passing
- ✅ 95% thin tool compliance achieved
- ✅ Documentation updated

#### Week 7: Phase 3 Core Testing Start (20-25 hours)
**Dates:** 2026-02-26 to 2026-03-05

- [ ] Day 1-3: server.py testing - Part 1 (6-8h)
  - Tool registration tests (10 tests)
  - Tool execution tests (10 tests)
  
- [ ] Day 4-5: server.py testing - Part 2 (6-7h)
  - P2P integration tests (8 tests)
  - Configuration tests (8 tests)
  - Error handling tests (8 tests)
  
- [ ] Day 6-7: hierarchical_tool_manager.py testing (6-8h)
  - Tool discovery tests (8 tests)
  - Tool access tests (7 tests)
  - ServerContext integration (5-10 tests)
  
- [ ] Day 8: Code review and cleanup (2h)

**Deliverables:**
- test_server_core.py (1,200+ lines, 40-50 tests)
- test_hierarchical_tool_manager.py (600+ lines, 20-25 tests)
- 60-75 total new tests
- 35-40% overall coverage

**Status Gate:** Week 7 complete when:
- ✅ 60-75 tests passing
- ✅ server.py coverage ≥75%
- ✅ hierarchical_tool_manager.py coverage ≥75%
- ✅ Overall MCP coverage ≥35%

#### Week 8: P2P and Configuration Testing (10-13 hours)
**Dates:** 2026-03-05 to 2026-03-12

- [ ] Day 1-2: p2p_mcp_registry_adapter.py testing (5-6h)
  - Tool discovery tests (8 tests)
  - Wrapper creation tests (7 tests)
  
- [ ] Day 3: p2p_service_manager.py testing (3-4h)
  - Service initialization (5 tests)
  - Workflow integration (5-10 tests)
  
- [ ] Day 4: fastapi_config.py testing (2-3h)
  - Configuration loading (5-8 tests)

**Deliverables:**
- test_p2p_adapter.py (400+ lines, 15-20 tests)
- test_p2p_manager.py (300+ lines, 10-15 tests)
- test_fastapi_config.py (200+ lines, 5-8 tests)
- 30-43 total new tests

**Status Gate:** Week 8 complete when:
- ✅ 30-43 tests passing
- ✅ P2P modules coverage ≥70%
- ✅ Overall MCP coverage ≥45%

#### Week 9: FastAPI and Tool Testing (14-18 hours)
**Dates:** 2026-03-12 to 2026-03-19

- [ ] Day 1-2: fastapi_service.py endpoint testing (4-5h)
  - Health check endpoint
  - Tool listing endpoint
  - Tool execution endpoint
  - Embedding generation endpoint
  
- [ ] Day 3-4: Sample tool testing (6-8h)
  - Test 10-15 representative tools
  - Validate thin wrapper pattern
  - Error handling
  
- [ ] Day 5-6: Performance testing (4-5h)
  - Startup time benchmarks
  - Tool execution latency
  - IPFS operation caching
  - Parallel throughput

**Deliverables:**
- test_fastapi_endpoints.py (400+ lines, 10-15 tests)
- test_tool_samples.py (600+ lines, 20-25 tests)
- test_performance.py (400+ lines, 10-15 tests)
- 40-55 total new tests

**Status Gate:** Week 9 complete when:
- ✅ 40-55 tests passing
- ✅ FastAPI coverage ≥70%
- ✅ Performance benchmarks passing
- ✅ Overall MCP coverage ≥55%

#### Week 10: Integration and Validation (16-22 hours)
**Dates:** 2026-03-19 to 2026-03-26

- [ ] Day 1-3: P2P integration testing (6-8h)
  - Workflow submission/execution
  - IPFS storage/retrieval
  - TaskQueue operations
  
- [ ] Day 4-5: End-to-end workflow testing (4-6h)
  - Complete workflows
  - Error recovery
  - Resource cleanup
  
- [ ] Day 6: Regression testing (2-3h)
  - Phase 1 security fixes
  - Phase 2 architecture changes
  
- [ ] Day 7: Documentation and cleanup (4-5h)
  - Update all documentation
  - Generate API docs
  - Final code review

**Deliverables:**
- test_p2p_integration.py (600+ lines, 15-20 tests)
- test_e2e_workflows.py (400+ lines, 10-15 tests)
- test_regressions.py (200+ lines, 10 tests)
- Updated documentation
- 35-45 total new tests

**Status Gate:** Week 10 complete when:
- ✅ 35-45 tests passing
- ✅ All integration tests passing
- ✅ Overall MCP coverage ≥60-75%
- ✅ Documentation complete

#### Weeks 11-12: Code Quality and Performance (16-20 hours)
**Dates:** 2026-03-26 to 2026-04-09

- [ ] Week 11: Code quality improvements (8-10h)
  - Complex function refactoring
  - Exception handling standardization
  - Type hint completion
  - Docstring completion (partial)
  
- [ ] Week 12: Performance optimization (8-10h)
  - Startup optimization
  - Tool execution parallelism
  - IPFS caching
  - Query optimization

**Deliverables:**
- All complex functions refactored (<50 lines)
- Zero bare exception handlers
- 100% type hint coverage
- 50%+ docstring coverage
- Performance targets achieved

### 12.3 Progress Tracking

**Weekly Checkpoints:**
- Monday: Review previous week progress
- Wednesday: Mid-week status check
- Friday: Weekly deliverables review

**Metrics Dashboard:**
- Test coverage (overall and per module)
- Test count (unit, integration, P2P, performance)
- Code quality metrics (complexity, exceptions, docstrings)
- Performance metrics (startup, latency, throughput)

**Reporting:**
- Weekly progress reports
- Bi-weekly stakeholder updates
- Monthly milestone reviews

---

## Appendix A: Quick Reference

### Key Contacts
- **Project Lead:** TBD
- **Code Reviewers:** TBD
- **Documentation:** TBD

### Important Links
- **Repository:** https://github.com/endomorphosis/ipfs_datasets_py
- **Branch:** copilot/refactor-improve-mcp-server
- **Documentation:** /ipfs_datasets_py/mcp_server/docs/
- **Tests:** /tests/mcp/

### Commands
```bash
# Run all MCP tests
pytest tests/mcp -v

# Run with coverage
pytest tests/mcp --cov=ipfs_datasets_py/mcp_server --cov-report=html

# Run specific test category
pytest tests/mcp -v -m unit
pytest tests/mcp -v -m integration
pytest tests/mcp -v -m performance

# Type checking
mypy ipfs_datasets_py/mcp_server --strict

# Linting
flake8 ipfs_datasets_py/mcp_server
pylint ipfs_datasets_py/mcp_server

# Complexity check
radon cc ipfs_datasets_py/mcp_server -a

# Documentation
sphinx-build -b html docs docs/_build
```

---

## Appendix B: Change Log

### Version 2.0 (2026-02-19)
- Initial comprehensive refactoring plan
- Detailed Phase 2 Week 6-7 planning
- Phase 3 testing strategy (Weeks 7-10)
- Code quality improvement roadmap
- Performance optimization plan
- Complete timeline with milestones

### Future Updates
- TBD based on implementation progress

---

**Document Status:** ACTIVE  
**Last Updated:** 2026-02-19  
**Next Review:** 2026-02-26 (after Week 6 completion)  
**Approval:** Pending  
**Version:** 2.0
