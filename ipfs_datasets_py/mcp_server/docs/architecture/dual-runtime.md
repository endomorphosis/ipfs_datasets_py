# MCP Server + MCP++ Architecture Integration

**Date:** 2026-02-17  
**Status:** DRAFT  

## Overview

This document describes the technical architecture for integrating MCP++ capabilities into the IPFS Datasets MCP server using a dual-runtime approach.

---

## 1. Current Architecture

### 1.1 Component Overview

```
┌─────────────────────────────────────────────────────────────┐
│                    IPFS Datasets MCP Server                  │
├─────────────────────────────────────────────────────────────┤
│                                                               │
│  ┌────────────────┐        ┌──────────────────┐            │
│  │   FastAPI      │───────▶│  Tool Registry   │            │
│  │   Server       │        │  (370+ tools)    │            │
│  └────────────────┘        └──────────────────┘            │
│         │                            │                       │
│         │                            │                       │
│         ▼                            ▼                       │
│  ┌────────────────┐        ┌──────────────────┐            │
│  │ Hierarchical   │        │   Tool Wrapper   │            │
│  │ Tool Manager   │◀──────▶│   & Validators   │            │
│  └────────────────┘        └──────────────────┘            │
│         │                            │                       │
│         │                            │                       │
│         ▼                            ▼                       │
│  ┌─────────────────────────────────────────┐               │
│  │        Tool Categories (73 dirs)        │               │
│  ├─────────────────────────────────────────┤               │
│  │ • dataset_tools  • ipfs_tools           │               │
│  │ • vector_tools   • graph_tools          │               │
│  │ • pdf_tools      • media_tools          │               │
│  │ • search_tools   • security_tools       │               │
│  │ • ... (65 more categories)              │               │
│  └─────────────────────────────────────────┘               │
│         │                            │                       │
│         │                            │                       │
│         ▼                            ▼                       │
│  ┌────────────────┐        ┌──────────────────┐            │
│  │ P2P Service    │───────▶│ P2P Registry     │            │
│  │ Manager        │        │ Adapter          │            │
│  │ (Basic)        │        │                  │            │
│  └────────────────┘        └──────────────────┘            │
│         │                                                    │
│         │ (Thread hop via trio_bridge)                     │
│         ▼                                                    │
│  ┌────────────────────────────────────────┐               │
│  │     Trio Runtime (for libp2p only)     │               │
│  └────────────────────────────────────────┘               │
│                                                               │
└─────────────────────────────────────────────────────────────┘
```

### 1.2 Current Flow (P2P Operations)

```
User Request (P2P tool)
    │
    ▼
FastAPI Handler (anyio)
    │
    ▼
Tool Registry Lookup
    │
    ▼
Tool Wrapper Execution
    │
    ▼
P2P Service Manager
    │
    ▼ (Thread hop #1)
trio_bridge.py
    │
    ▼ (Thread hop #2)
Trio Runtime (libp2p)
    │
    ▼
P2P Operation
    │
    ▼ (Thread hop #3)
Return to FastAPI
    │
    ▼
Response to User
```

**Latency:** ~150-250ms (including ~50-100ms from thread hops)

---

## 2. Target Architecture (Dual Runtime)

### 2.1 Component Overview

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         IPFS Datasets MCP Server                         │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                           │
│  ┌───────────────────────────────────────────────────────────┐          │
│  │              Unified Tool Registry (390+ tools)            │          │
│  │  • 370 general tools  • 20 P2P tools (from MCP++)        │          │
│  └───────────────────────────────────────────────────────────┘          │
│                           │                                               │
│                           │ Route based on tool type                    │
│                           │                                               │
│           ┌───────────────┴─────────────────┐                           │
│           │                                   │                           │
│           ▼                                   ▼                           │
│  ┌──────────────────┐              ┌──────────────────┐                │
│  │  FastAPI Runtime │              │  Trio Runtime    │                │
│  │    (anyio)       │              │   (Native)       │                │
│  └──────────────────┘              └──────────────────┘                │
│           │                                   │                           │
│           │                                   │                           │
│           ▼                                   ▼                           │
│  ┌──────────────────┐              ┌──────────────────┐                │
│  │  General Tools   │              │   P2P Tools      │                │
│  │  (370 tools)     │              │   (20 tools)     │                │
│  │                  │              │                  │                │
│  │ • Dataset ops    │              │ • Workflow       │                │
│  │ • IPFS ops       │              │ • Task queue     │                │
│  │ • Vector ops     │              │ • Peer mgmt      │                │
│  │ • Graph ops      │              │ • Bootstrap      │                │
│  │ • PDF ops        │              │                  │                │
│  │ • Media ops      │              │                  │                │
│  │ • Search ops     │              │                  │                │
│  │ • etc.           │              │                  │                │
│  └──────────────────┘              └──────────────────┘                │
│           │                                   │                           │
│           │                                   │                           │
│           └────────────┬──────────────────────┘                          │
│                        │                                                  │
│                        ▼                                                  │
│              ┌───────────────────┐                                       │
│              │  Shared Services  │                                       │
│              ├───────────────────┤                                       │
│              │ • Configuration   │                                       │
│              │ • Authentication  │                                       │
│              │ • Monitoring      │                                       │
│              │ • Logging         │                                       │
│              └───────────────────┘                                       │
│                                                                           │
└─────────────────────────────────────────────────────────────────────────┘
```

### 2.2 Target Flow (P2P Operations)

```
User Request (P2P tool)
    │
    ▼
Unified Tool Registry
    │
    ▼
Runtime Router (detects P2P tool)
    │
    ▼ (DIRECT - no thread hops!)
Trio Runtime
    │
    ▼
P2P Tool Execution
    │
    ▼
MCP++ Module (workflow/taskqueue/peers)
    │
    ▼
libp2p Operation
    │
    ▼ (DIRECT return)
Response to User
```

**Latency:** ~50-100ms (50-70% reduction)

### 2.3 Component Details

#### 2.3.1 Runtime Router

**Location:** `ipfs_datasets_py/mcp_server/runtime_router.py`

**Responsibilities:**
- Detect tool type (general vs P2P)
- Route to appropriate runtime
- Handle runtime unavailability
- Provide fallback mechanisms

**Implementation:**
```python
class RuntimeRouter:
    def __init__(self):
        self.fastapi_runtime = FastAPIRuntime()
        self.trio_runtime = TrioRuntime() if HAVE_TRIO else None
        self.p2p_tools = {
            'submit_workflow', 'get_workflow_status', ...
        }
    
    async def route(self, tool_name: str, args: dict) -> Any:
        if tool_name in self.p2p_tools and self.trio_runtime:
            return await self.trio_runtime.execute(tool_name, args)
        else:
            return await self.fastapi_runtime.execute(tool_name, args)
```

#### 2.3.2 MCP++ Module Integration

**Location:** `ipfs_datasets_py/mcp_server/mcplusplus/`

**Structure:**
```
mcplusplus/
├── __init__.py              # Module exports
├── workflow_scheduler.py    # Wrapper around mcplusplus_module.p2p.workflow
├── task_queue.py            # Enhanced task queue
├── peer_registry.py         # Peer discovery wrapper
├── bootstrap.py             # Bootstrap helpers
├── connectivity.py          # Connection management
└── runtime_adapter.py       # Trio runtime adapter
```

**Import Strategy:**
```python
# Graceful imports with fallback
try:
    from ipfs_accelerate_py.mcplusplus_module.p2p import (
        P2PWorkflowScheduler,
        P2PTaskQueue,
        PeerRegistry,
    )
    HAVE_MCPLUSPLUS = True
except ImportError:
    HAVE_MCPLUSPLUS = False
    # Fallback to basic implementations
```

#### 2.3.3 Enhanced P2P Service Manager

**Location:** `ipfs_datasets_py/mcp_server/p2p_service_manager.py`

**Enhancements:**
1. **Workflow Scheduler Integration**
   ```python
   class P2PServiceManager:
       def __init__(self, ...):
           # ... existing code ...
           self._workflow_scheduler = None
           
       async def start_workflow_scheduler(self):
           if not HAVE_MCPLUSPLUS:
               return
           
           from .mcplusplus.workflow_scheduler import create_scheduler
           self._workflow_scheduler = create_scheduler(...)
           await self._workflow_scheduler.start()
   ```

2. **Peer Registry Integration**
   ```python
   async def start_peer_registry(self):
       if not HAVE_MCPLUSPLUS:
           return
       
       from .mcplusplus.peer_registry import create_registry
       self._peer_registry = create_registry(...)
       await self._peer_registry.start()
   ```

3. **Graceful Degradation**
   ```python
   @property
   def has_advanced_features(self) -> bool:
       return HAVE_MCPLUSPLUS and self._workflow_scheduler is not None
   ```

---

## 3. Integration Patterns

### 3.1 Tool Registration Pattern

**Problem:** Need to register both FastAPI and Trio tools in unified registry

**Solution:** Dual registration with runtime metadata

```python
# In tool_registry.py
class UnifiedToolRegistry:
    def __init__(self):
        self.tools: Dict[str, ToolDescriptor] = {}
    
    def register(
        self, 
        name: str, 
        func: Callable,
        runtime: Literal["fastapi", "trio"] = "fastapi",
        category: str = "general"
    ):
        self.tools[name] = ToolDescriptor(
            name=name,
            function=func,
            runtime=runtime,
            category=category,
            schema=extract_schema(func),
        )
    
    def register_p2p_tools(self):
        """Register MCP++ P2P tools for Trio runtime."""
        if not HAVE_MCPLUSPLUS:
            return
        
        from .mcplusplus.tools import (
            submit_workflow,
            get_workflow_status,
            # ... 18 more
        )
        
        self.register("submit_workflow", submit_workflow, 
                     runtime="trio", category="p2p_workflow")
        # ... register others
```

### 3.2 Configuration Pattern

**Problem:** Need to configure both runtimes separately

**Solution:** Hierarchical configuration

```yaml
# config.yaml
server:
  host: "0.0.0.0"
  port: 8000
  
runtimes:
  fastapi:
    enabled: true
    workers: 4
    timeout: 60
  
  trio:
    enabled: true
    # Enable when HAVE_MCPLUSPLUS=true
    enable_on_import: true
    
p2p:
  enabled: true
  workflow_scheduler:
    enabled: true
    max_concurrent_workflows: 100
  task_queue:
    enabled: true
    queue_path: "~/.cache/ipfs_datasets_py/task_queue.duckdb"
  peer_registry:
    enabled: true
    bootstrap_nodes:
      - "/ip4/127.0.0.1/tcp/4001/p2p/QmBootstrap1"
```

### 3.3 Monitoring Pattern

**Problem:** Need to monitor both runtimes

**Solution:** Unified metrics with runtime tags

```python
# In monitoring.py
class UnifiedMonitoring:
    def record_tool_execution(
        self,
        tool_name: str,
        runtime: str,
        duration_ms: float,
        success: bool,
    ):
        self.metrics.counter(
            "tool_execution_total",
            tags={
                "tool": tool_name,
                "runtime": runtime,
                "status": "success" if success else "error",
            }
        ).inc()
        
        self.metrics.histogram(
            "tool_execution_duration_ms",
            tags={
                "tool": tool_name,
                "runtime": runtime,
            }
        ).observe(duration_ms)
```

### 3.4 Error Handling Pattern

**Problem:** Different error types from different runtimes

**Solution:** Unified exception hierarchy

```python
# In exceptions.py
class MCPServerError(Exception):
    """Base exception for MCP server."""
    pass

class ToolExecutionError(MCPServerError):
    """Tool execution failed."""
    def __init__(self, tool_name: str, runtime: str, cause: Exception):
        self.tool_name = tool_name
        self.runtime = runtime
        self.cause = cause
        super().__init__(
            f"Tool {tool_name} failed on {runtime} runtime: {cause}"
        )

class RuntimeUnavailableError(MCPServerError):
    """Requested runtime is unavailable."""
    pass
```

---

## 4. Data Flow Diagrams

### 4.1 Tool Execution Flow (General Tool)

```
┌─────────┐
│  User   │
└────┬────┘
     │ HTTP POST /tools/execute
     │ {"tool": "load_dataset", "args": {...}}
     ▼
┌──────────────────┐
│  FastAPI Handler │
└────┬─────────────┘
     │
     ▼
┌──────────────────┐
│  Tool Registry   │
│  Lookup          │
└────┬─────────────┘
     │ tool_descriptor.runtime = "fastapi"
     ▼
┌──────────────────┐
│  Runtime Router  │
│  (detects        │
│   fastapi)       │
└────┬─────────────┘
     │
     ▼
┌──────────────────┐
│  FastAPI Runtime │
│  Executor        │
└────┬─────────────┘
     │
     ▼
┌──────────────────┐
│  load_dataset()  │
│  function        │
└────┬─────────────┘
     │
     ▼
┌──────────────────┐
│  Return result   │
└────┬─────────────┘
     │
     ▼
┌──────────────────┐
│  User Response   │
└──────────────────┘
```

### 4.2 Tool Execution Flow (P2P Tool)

```
┌─────────┐
│  User   │
└────┬────┘
     │ HTTP POST /tools/execute
     │ {"tool": "submit_workflow", "args": {...}}
     ▼
┌──────────────────┐
│  FastAPI Handler │
└────┬─────────────┘
     │
     ▼
┌──────────────────┐
│  Tool Registry   │
│  Lookup          │
└────┬─────────────┘
     │ tool_descriptor.runtime = "trio"
     ▼
┌──────────────────┐
│  Runtime Router  │
│  (detects trio)  │
└────┬─────────────┘
     │ DIRECT call (no thread hop!)
     ▼
┌──────────────────┐
│  Trio Runtime    │
│  Executor        │
└────┬─────────────┘
     │
     ▼
┌──────────────────┐
│  MCP++ Module    │
│  submit_workflow │
└────┬─────────────┘
     │
     ▼
┌──────────────────┐
│ P2P Workflow     │
│ Scheduler        │
└────┬─────────────┘
     │
     ▼
┌──────────────────┐
│  libp2p network  │
└────┬─────────────┘
     │ DIRECT return
     ▼
┌──────────────────┐
│  User Response   │
└──────────────────┘
```

### 4.3 P2P Workflow Execution Flow

```
┌────────────────┐
│ submit_workflow│
│ tool called    │
└───────┬────────┘
        │
        ▼
┌─────────────────────┐
│ P2P Workflow        │
│ Scheduler           │
│ (MCP++ module)      │
└───────┬─────────────┘
        │
        ▼
┌─────────────────────┐
│ Create Workflow DAG │
│ with Merkle Clock   │
└───────┬─────────────┘
        │
        ▼
┌─────────────────────┐
│ Task Queue Submit   │
│ (split into tasks)  │
└───────┬─────────────┘
        │
        ▼
┌─────────────────────┐
│ Peer Registry       │
│ Select Best Peers   │
└───────┬─────────────┘
        │
        ▼
┌─────────────────────┐
│ libp2p Connection   │
│ to Selected Peers   │
└───────┬─────────────┘
        │
        ▼
┌─────────────────────┐
│ Distribute Tasks    │
│ to Peers            │
└───────┬─────────────┘
        │
        ▼
┌─────────────────────┐
│ Monitor Execution   │
│ & Collect Results   │
└───────┬─────────────┘
        │
        ▼
┌─────────────────────┐
│ Return Workflow ID  │
│ to User             │
└─────────────────────┘
```

---

## 5. Deployment Architecture

### 5.1 Single-Node Deployment

```
┌─────────────────────────────────────────────────┐
│              Server Host                         │
├─────────────────────────────────────────────────┤
│                                                  │
│  ┌──────────────────────────────────────────┐  │
│  │     IPFS Datasets MCP Server Process     │  │
│  ├──────────────────────────────────────────┤  │
│  │                                           │  │
│  │  ┌─────────────┐    ┌─────────────┐    │  │
│  │  │  FastAPI    │    │   Trio      │    │  │
│  │  │  Runtime    │    │   Runtime   │    │  │
│  │  │             │    │   (MCP++)   │    │  │
│  │  └─────────────┘    └─────────────┘    │  │
│  │                                           │  │
│  └──────────────────────────────────────────┘  │
│                     │                            │
│                     │                            │
│                     ▼                            │
│  ┌──────────────────────────────────────────┐  │
│  │          Local DuckDB Queue              │  │
│  │  ~/.cache/ipfs_datasets_py/              │  │
│  └──────────────────────────────────────────┘  │
│                                                  │
└─────────────────────────────────────────────────┘
         │                              │
         │                              │
         ▼                              ▼
  (HTTP Clients)                 (libp2p Peers)
```

### 5.2 Multi-Node Deployment

```
┌─────────────────────────────────────────────────┐
│              Load Balancer                       │
└──────────────┬──────────────────┬───────────────┘
               │                  │
       ┌───────┴────────┐  ┌─────┴──────────┐
       │                │  │                 │
       ▼                ▼  ▼                 ▼
┌─────────────┐  ┌─────────────┐  ┌─────────────┐
│  Server 1   │  │  Server 2   │  │  Server N   │
│  (MCP+MCP++)│  │  (MCP+MCP++)│  │  (MCP+MCP++)│
└──────┬──────┘  └──────┬──────┘  └──────┬──────┘
       │                │                 │
       └────────────────┴─────────────────┘
                        │
                        ▼
              ┌──────────────────┐
              │ Shared DuckDB or │
              │ Distributed Queue│
              └──────────────────┘
                        │
                        │
       ┌────────────────┼────────────────┐
       │                │                 │
       ▼                ▼                 ▼
┌─────────────┐  ┌─────────────┐  ┌─────────────┐
│  P2P Peer 1 │  │  P2P Peer 2 │  │  P2P Peer N │
└─────────────┘  └─────────────┘  └─────────────┘
```

### 5.3 Container Deployment (Docker)

```yaml
# docker-compose.yml
version: '3.8'

services:
  mcp-server:
    image: ipfs-datasets-mcp:latest
    ports:
      - "8000:8000"
      - "4001:4001"  # libp2p
    environment:
      - ENABLE_MCPLUSPLUS=true
      - MCP_HOST=0.0.0.0
      - MCP_PORT=8000
      - P2P_LISTEN_PORT=4001
      - TASK_QUEUE_PATH=/data/task_queue.duckdb
    volumes:
      - mcp-data:/data
      - mcp-cache:/root/.cache
    networks:
      - mcp-network
  
  bootstrap-peer:
    image: ipfs-datasets-mcp:latest
    command: ["python", "-m", "ipfs_datasets_py.mcp_server.mcplusplus.bootstrap"]
    ports:
      - "4002:4001"
    networks:
      - mcp-network

volumes:
  mcp-data:
  mcp-cache:

networks:
  mcp-network:
    driver: bridge
```

---

## 6. Migration Strategy

### 6.1 Phase 1: Foundation (No Breaking Changes)

**Changes:**
- Add MCP++ import adapters (graceful fallback)
- Extend P2P service manager (backward compatible)
- Add runtime router (default to FastAPI)

**User Impact:** NONE (all changes internal)

**Rollback:** Simple (feature flag)

### 6.2 Phase 2: P2P Enhancement (Opt-in)

**Changes:**
- Add 20 P2P tools from MCP++
- Enable Trio runtime (opt-in via config)
- Add peer management tools

**User Impact:** LOW (opt-in feature)

**Configuration:**
```yaml
p2p:
  enabled: true  # Existing config
  mcplusplus:
    enabled: true  # NEW: opt-in to MCP++ features
```

**Rollback:** Simple (disable via config)

### 6.3 Phase 3: Performance (Transparent)

**Changes:**
- Optimize tool routing
- Add connection pooling
- Enable direct Trio execution for P2P tools

**User Impact:** POSITIVE (faster P2P operations)

**Rollback:** Moderate (need to revert routing logic)

### 6.4 Phase 4: Advanced Features (Opt-in)

**Changes:**
- Add event provenance
- Add content-addressed contracts
- Add UCAN capabilities

**User Impact:** LOW (opt-in features)

**Rollback:** Simple (disable via config)

---

## 7. Testing Strategy

### 7.1 Unit Tests

```python
# tests/test_runtime_router.py
class TestRuntimeRouter:
    def test_routes_p2p_tool_to_trio(self):
        router = RuntimeRouter()
        tool_name = "submit_workflow"
        
        result = router.detect_runtime(tool_name)
        
        assert result == "trio"
    
    def test_routes_general_tool_to_fastapi(self):
        router = RuntimeRouter()
        tool_name = "load_dataset"
        
        result = router.detect_runtime(tool_name)
        
        assert result == "fastapi"
    
    def test_fallback_when_trio_unavailable(self):
        router = RuntimeRouter(trio_available=False)
        tool_name = "submit_workflow"
        
        result = router.detect_runtime(tool_name)
        
        assert result == "fastapi"  # Fallback
```

### 7.2 Integration Tests

```python
# tests/test_dual_runtime_integration.py
@pytest.mark.asyncio
async def test_p2p_workflow_execution():
    """Test end-to-end P2P workflow execution."""
    # GIVEN: MCP server with dual runtime
    server = create_test_server(enable_mcplusplus=True)
    
    # WHEN: Submit workflow via P2P tool
    result = await server.execute_tool(
        "submit_workflow",
        {
            "workflow_name": "test-workflow",
            "tasks": [{"task": "inference", "model": "gpt2"}]
        }
    )
    
    # THEN: Workflow submitted successfully
    assert result["status"] == "success"
    assert "workflow_id" in result
    
    # AND: Executed on Trio runtime (not FastAPI)
    assert result["_runtime"] == "trio"
    
    # AND: Latency is reduced
    assert result["_duration_ms"] < 100
```

### 7.3 Performance Tests

```python
# tests/test_performance_benchmarks.py
@pytest.mark.benchmark
def test_p2p_operation_latency(benchmark):
    """Benchmark P2P operation latency."""
    server = create_test_server(enable_mcplusplus=True)
    
    def submit_workflow():
        return server.execute_tool_sync("submit_workflow", {...})
    
    result = benchmark(submit_workflow)
    
    # Target: <100ms
    assert benchmark.stats.mean < 0.1
```

---

## 8. Monitoring & Observability

### 8.1 Metrics

**Runtime Metrics:**
- `mcp_runtime_active{runtime="fastapi|trio"}` - Runtime status
- `mcp_tool_execution_total{runtime, tool, status}` - Tool execution count
- `mcp_tool_execution_duration_ms{runtime, tool}` - Tool execution duration
- `mcp_runtime_errors_total{runtime, error_type}` - Runtime errors

**P2P Metrics:**
- `mcp_p2p_peers_connected` - Connected peers
- `mcp_p2p_workflows_active` - Active workflows
- `mcp_p2p_tasks_queued` - Queued tasks
- `mcp_p2p_task_execution_duration_ms` - Task execution time

### 8.2 Logging

**Log Levels:**
- `DEBUG`: Detailed runtime routing decisions
- `INFO`: Tool executions, P2P operations
- `WARNING`: Fallbacks, degraded performance
- `ERROR`: Tool failures, runtime errors

**Log Format:**
```json
{
  "timestamp": "2026-02-17T19:25:31Z",
  "level": "INFO",
  "runtime": "trio",
  "tool": "submit_workflow",
  "duration_ms": 45,
  "status": "success",
  "workflow_id": "wf-12345"
}
```

### 8.3 Tracing

**Distributed Tracing:**
- Trace P2P operations across nodes
- Track tool execution chains
- Identify performance bottlenecks

**OpenTelemetry Integration:**
```python
from opentelemetry import trace

tracer = trace.get_tracer(__name__)

async def execute_tool(tool_name: str, args: dict):
    with tracer.start_as_current_span("execute_tool") as span:
        span.set_attribute("tool.name", tool_name)
        span.set_attribute("runtime", detect_runtime(tool_name))
        
        result = await _execute_tool_impl(tool_name, args)
        
        span.set_attribute("status", result["status"])
        return result
```

---

## 9. Security Considerations

### 9.1 Runtime Isolation

**Problem:** Different runtimes may have different security contexts

**Solution:**
- Shared authentication/authorization
- Runtime-specific sandboxing
- Resource limits per runtime

### 9.2 P2P Security

**Problem:** P2P operations open attack surface

**Solution:**
- Authentication tokens for P2P calls
- Peer reputation system
- Rate limiting per peer
- Network segmentation

### 9.3 Configuration Security

**Problem:** Sensitive configuration in YAML files

**Solution:**
- Environment variable substitution
- Secret management integration
- Configuration validation

---

## 10. Appendices

### 10.1 File Structure

```
ipfs_datasets_py/mcp_server/
├── __init__.py
├── server.py                    # Main server (unchanged)
├── configs.py                   # Configuration (enhanced)
├── runtime_router.py            # NEW: Runtime routing logic
├── p2p_service_manager.py       # ENHANCED: MCP++ integration
├── p2p_mcp_registry_adapter.py  # ENHANCED: Support Trio tools
├── hierarchical_tool_manager.py # ENHANCED: Dual runtime support
├── tool_registry.py             # ENHANCED: Runtime metadata
├── monitoring.py                # ENHANCED: Dual runtime metrics
│
├── mcplusplus/                  # NEW: MCP++ integration layer
│   ├── __init__.py
│   ├── workflow_scheduler.py
│   ├── task_queue.py
│   ├── peer_registry.py
│   ├── bootstrap.py
│   ├── connectivity.py
│   └── runtime_adapter.py
│
├── tools/
│   ├── ... (existing 73 categories)
│   ├── p2p_workflow_tools/      # NEW: From MCP++
│   ├── p2p_taskqueue_tools/     # NEW: From MCP++
│   └── peer_management_tools/   # NEW: From MCP++
│
└── docs/
    ├── ARCHITECTURE_INTEGRATION.md  # This file
    ├── MCP_IMPROVEMENT_PLAN.md
    └── P2P_MIGRATION_GUIDE.md
```

### 10.2 Dependency Updates

**New Dependencies:**
```
# requirements.txt additions
ipfs-accelerate-py>=0.1.0  # MCP++ module source
trio>=0.22.0                # Native async runtime (may already exist)
hypercorn>=0.14.0           # ASGI server with Trio support
```

### 10.3 Configuration Reference

**Complete Configuration Example:**
```yaml
# config.yaml
server:
  host: "0.0.0.0"
  port: 8000
  log_level: "INFO"
  
runtimes:
  fastapi:
    enabled: true
    workers: 4
    timeout: 60
  
  trio:
    enabled: true
    enable_on_import: true
    
tools:
  enabled_categories:
    - all  # or specific categories
  
p2p:
  enabled: true
  
  mcplusplus:
    enabled: true  # Enable MCP++ features
    
  workflow_scheduler:
    enabled: true
    max_concurrent_workflows: 100
    workflow_timeout: 3600
    
  task_queue:
    enabled: true
    queue_path: "~/.cache/ipfs_datasets_py/task_queue.duckdb"
    max_queue_size: 10000
    
  peer_registry:
    enabled: true
    bootstrap_nodes:
      - "/ip4/127.0.0.1/tcp/4001/p2p/QmBootstrap1"
    peer_discovery_interval: 60
    
  connectivity:
    listen_port: 4001
    max_connections: 100
    connection_timeout: 30
    
monitoring:
  enabled: true
  metrics_port: 9090
  enable_tracing: true
  tracing_endpoint: "http://localhost:4318"
```

---

**Document Version:** 1.0  
**Last Updated:** 2026-02-17  
**Status:** DRAFT - Technical Design
