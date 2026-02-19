# IPFS Datasets MCP Server

This package provides a Model Context Protocol (MCP) server implementation for IPFS Datasets Python, enabling AI models like Claude to interact with IPFS datasets through standardized tools.

---

## 🎯 Current Status (2026-02-19)

**Progress:** 60% Complete - Production Refactoring in Progress  
**Test Coverage:** 25-35% (Target: 75%+)  
**Security:** ✅ Phase 1 Complete - All 5 critical vulnerabilities FIXED  
**Architecture:** ✅ Excellent - Hierarchical tools, thin wrappers, dual-runtime operational

---

## 📚 Documentation Quick Guide

### 🚀 **For New Contributors** → Start Here!
- **[QUICK_REFERENCE_CARD_v3.md](QUICK_REFERENCE_CARD_v3.md)** (8KB) - Quick overview, how to contribute, common commands

### 📊 **Status & Planning**
- **[REFACTORING_EXECUTIVE_SUMMARY_v3_2026.md](REFACTORING_EXECUTIVE_SUMMARY_v3_2026.md)** (8KB) - Current status, priorities, roadmap
- **[VISUAL_REFACTORING_SUMMARY_v3_2026.md](VISUAL_REFACTORING_SUMMARY_v3_2026.md)** (12KB) - Visual progress dashboard

### 📖 **Detailed Planning**
- **[COMPREHENSIVE_REFACTORING_AND_IMPROVEMENT_PLAN_2026_v3.md](COMPREHENSIVE_REFACTORING_AND_IMPROVEMENT_PLAN_2026_v3.md)** (47KB) - Complete roadmap with testing strategy, code quality standards, risk management

### 🏗️ **Architecture**
- **[THIN_TOOL_ARCHITECTURE.md](THIN_TOOL_ARCHITECTURE.md)** - Architecture patterns and guidelines

### 📋 **Legacy Docs** (Reference Only)
- Previous refactoring plans v1 and v2
- Completion summaries and phase tracking

---

## 🔥 Current Priority: Phase 3 Testing

**Week 11 Sprint:** FastAPI Service Testing
- **Need:** 15-18 new tests for endpoints, authentication, error handling
- **Effort:** 8-10 hours
- **Priority:** 🔴 CRITICAL (blocking production)

**See:** [Week 11 details in Quick Reference Card](QUICK_REFERENCE_CARD_v3.md#-current-sprint-goals)

---

## ✅ Completed Achievements

### Phase 1: Security Hardening ✅ (100% Complete)
- ✅ Fixed 5 critical security vulnerabilities
- ✅ Hardcoded secrets eliminated
- ✅ Bare exceptions in critical paths fixed
- ✅ Subprocess sanitization implemented
- ✅ Error report sanitization added

### Architecture Excellence ✅ (90%+ Complete)
- ✅ **Hierarchical Tool Manager** - 99% context reduction (373→4 tools)
- ✅ **Thin Wrapper Pattern** - 318/321 tools compliant (99%)
- ✅ **Dual-Runtime System** - FastAPI + Trio for 50-70% P2P speedup
- ✅ **MCP++ Integration** - P2P workflows with graceful degradation
- ✅ **148 Tests Passing** - Comprehensive test suite established

---

## ⚠️ Remaining Work (14-16 weeks, 80-110 hours)

### Phase 3: Test Coverage (Weeks 11-14, 25-32h)
Achieve 75%+ coverage with 45-55 new tests:
- Week 11: FastAPI service (15-18 tests)
- Week 12: Trio runtime (12-15 tests)
- Week 13: Validators & monitoring (10-12 tests)
- Week 14: Integration & E2E (8-10 tests)

### Phase 4: Code Quality (Weeks 15-18, 27-38h)
- Refactor 8 complex functions (>100 lines)
- Fix 10+ bare exception handlers
- Add 120+ missing docstrings

### Phase 5-7: Final Polish (Weeks 19-24, 38-52h)
- Refactor 3 thick tools (2,274→250 lines)
- Consolidate duplicate code
- Complete documentation (90%+ coverage)
- Performance optimization
- Enhanced monitoring

---

## 🏗️ Architecture Overview

### Core Components

**Server Infrastructure:**
- `server.py` - Main MCP server using FastMCP (926 lines)
- `hierarchical_tool_manager.py` - 99% context reduction (536 lines)
- `fastapi_service.py` - REST API runtime (1,152 lines)
- `trio_adapter.py` / `trio_bridge.py` - Trio runtime for P2P (550 lines)
- `runtime_router.py` - Dual-runtime dispatch (400 lines)

**Tool Management:**
- **50 tool categories** with **321 tool files**
- **4 meta-tools** expose all functionality
- Dynamic loading, lazy initialization
- CLI-style tool naming (category/operation)

**P2P Integration (MCP++):**
- Workflow scheduler, task queue, peer registry
- 50-70% latency reduction for P2P operations
- Graceful degradation when unavailable
- Native Trio integration

**Configuration & Monitoring:**
- `server_context.py` - Server state management
- `validators.py` - Input validation
- `monitoring.py` - Metrics and observability

### Architecture Patterns

**1. Hierarchical Tools (99% context reduction)**
```python
# Instead of 321 tools, expose only 4 meta-tools:
mcp.add_tool(tools_list_categories)  # List all 50 categories
mcp.add_tool(tools_list_tools)       # List tools in a category
mcp.add_tool(tools_get_schema)       # Get tool schema
mcp.add_tool(tools_dispatch)         # Execute any tool
```

**2. Thin Wrapper Pattern (<150 lines per tool)**
```python
# Business logic in core module (reusable)
class DatasetLoader:
    def load(self, source: str) -> Dataset:
        # Business logic here
        pass

# MCP tool is thin wrapper (orchestration only)
@tool_metadata(runtime="fastapi")
async def load_dataset(source: str):
    loader = DatasetLoader()
    return await loader.load(source)
```

**3. Dual-Runtime System**
```python
# FastAPI runtime for general tools
@tool_metadata(runtime="fastapi")
async def general_tool(): pass

# Trio runtime for P2P tools (50-70% faster)
@tool_metadata(runtime="trio")
async def p2p_tool(): pass
```

**4. Graceful Degradation**
```python
# P2P features work even when dependencies unavailable
try:
    from ipfs_accelerate_py import TaskQueue
    HAS_P2P = True
except ImportError:
    HAS_P2P = False
    # Mock fallback with clear error messages
```

---

## 🧪 Testing

### Current Status
- **148 tests passing** across 20 test files
- **5,597 lines** of test code
- **Test coverage:** 25-35% (Target: 75%+)

### Test Structure
```
tests/mcp/
├── unit/              # Component unit tests
│   ├── test_server_core.py (40 tests)
│   ├── test_hierarchical_tool_manager.py (26 tests)
│   ├── test_p2p_service_manager.py (15 tests)
│   └── test_p2p_mcp_registry_adapter.py (26 tests)
├── integration/       # Integration tests
│   └── test_p2p_integration.py (6 tests)
├── e2e/               # End-to-end tests
│   ├── test_full_tool_lifecycle.py (10 tests)
│   ├── test_distributed_workflows.py (10 tests)
│   └── test_real_world_scenarios.py (7 tests)
└── [13 component test files] (200+ tests)
```

### Running Tests
```bash
# All tests
pytest tests/mcp/ -v

# With coverage
pytest tests/mcp/ --cov=ipfs_datasets_py.mcp_server --cov-report=html

# Specific component
pytest tests/mcp/unit/test_server_core.py -v

# Unit tests only (fast)
pytest tests/mcp/unit/ -v
```

---

## 🚀 Getting Started

### Installation
```bash
pip install -e ".[mcp]"  # MCP server dependencies
```

### Running the Server
```bash
# Main server
python -m ipfs_datasets_py.mcp_server

# Standalone server
python ipfs_datasets_py/mcp_server/standalone_server.py

# Simple server (lightweight)
python ipfs_datasets_py/mcp_server/simple_server.py
```

### Using the Hierarchical Tool System
```python
# List all categories
categories = tools_list_categories()
# Returns: ['dataset_tools', 'search_tools', 'graph_tools', ...]

# List tools in a category
tools = tools_list_tools("dataset_tools")
# Returns: ['load_dataset', 'save_dataset', 'convert_dataset', ...]

# Get tool schema
schema = tools_get_schema("dataset_tools", "load_dataset")
# Returns: Full schema with parameters, types, descriptions

# Execute a tool
result = tools_dispatch("dataset_tools", "load_dataset", {
    "source": "squad",
    "split": "train"
})
```

---

## 🤝 Contributing

### Quick Start for Contributors
1. Read [QUICK_REFERENCE_CARD_v3.md](QUICK_REFERENCE_CARD_v3.md)
2. Check current sprint goals (Week 11: FastAPI testing)
3. Pick a task from the refactoring plan
4. Follow testing patterns (GIVEN-WHEN-THEN)
5. Ensure all tests pass before committing

### Code Standards
- Functions <100 lines
- No bare exception handlers
- Comprehensive docstrings
- Type hints on all parameters/returns
- Test coverage maintained/improved

### Before Committing
```bash
# Run tests
pytest tests/mcp/ -v

# Check coverage
pytest tests/mcp/ --cov=ipfs_datasets_py.mcp_server

# Type checking
mypy ipfs_datasets_py/mcp_server/

# Linting
flake8 ipfs_datasets_py/mcp_server/
```

---

## 📈 Progress Tracking

### Overall Status: 60% Complete

```
Phase 1: Security          ████████████████████████ 100% ✅
Phase 2: Architecture      ████████████████░░░░░░░░  69% ⚠️
Phase 3: Testing           ███████████░░░░░░░░░░░░░  48% ⚠️
Phase 4: Quality           █████░░░░░░░░░░░░░░░░░░░  20% ⏳
Phase 5: Cleanup           ░░░░░░░░░░░░░░░░░░░░░░░░   0% ⏳
Phase 6: Documentation     ████████░░░░░░░░░░░░░░░░  40% ⏳
Phase 7: Performance       ░░░░░░░░░░░░░░░░░░░░░░░░   0% ⏳
```

**See:** [VISUAL_REFACTORING_SUMMARY_v3_2026.md](VISUAL_REFACTORING_SUMMARY_v3_2026.md) for detailed progress

---

## 📞 Support & Resources

### Documentation
- **Quick Start:** [QUICK_REFERENCE_CARD_v3.md](QUICK_REFERENCE_CARD_v3.md)
- **Planning:** [REFACTORING_EXECUTIVE_SUMMARY_v3_2026.md](REFACTORING_EXECUTIVE_SUMMARY_v3_2026.md)
- **Architecture:** [THIN_TOOL_ARCHITECTURE.md](THIN_TOOL_ARCHITECTURE.md)
- **Complete Plan:** [COMPREHENSIVE_REFACTORING_AND_IMPROVEMENT_PLAN_2026_v3.md](COMPREHENSIVE_REFACTORING_AND_IMPROVEMENT_PLAN_2026_v3.md)

### Key Metrics
- **Test Coverage:** 25-35% → Target: 75%+
- **Tool Categories:** 50 categories, 321 tools
- **Context Reduction:** 99% (373→4 meta-tools)
- **Thin Wrapper Compliance:** 99% (318/321 tools)

---

## 🎯 Next Steps

1. **Week 11:** FastAPI service testing (15-18 tests, 8-10 hours)
2. **Week 12:** Trio runtime testing (12-15 tests, 6-8 hours)
3. **Week 13:** Validators & monitoring tests (10-12 tests, 5-6 hours)
4. **Week 14:** Integration & E2E tests (8-10 tests, 6-8 hours)

**Goal:** Achieve 75%+ test coverage for production readiness

---

**Version:** 3.0  
**Last Updated:** 2026-02-19  
**Status:** Active Development - 60% Complete


We have created a comprehensive improvement plan to integrate advanced P2P capabilities from the [ipfs_accelerate_py MCP++ module](https://github.com/endomorphosis/ipfs_accelerate_py/tree/main/ipfs_accelerate_py/mcplusplus_module). This will bring:

- **50-70% reduction** in P2P operation latency (from ~200ms to 60-100ms)
- **30+ new P2P tools** (workflow scheduler, task queue, peer management, bootstrap)
- **Dual-runtime architecture** (FastAPI + Trio) for optimal performance
- **100% backward compatibility** with existing 370+ tools
- **3-4x throughput** increase for P2P operations
- **40% memory reduction** through structured concurrency

**📖 Planning Documentation:**
- [**🎯 Executive Summary**](./MCP_MCPLUSPLUS_EXECUTIVE_SUMMARY.md) - High-level overview (10KB, 5 min read)
- [**📋 Quick Reference**](./MCP_MCPLUSPLUS_QUICK_REFERENCE.md) - Implementation checklist (10KB, quick scan)
- [**📚 Complete Plan**](./MCP_MCPLUSPLUS_IMPROVEMENT_PLAN.md) - Detailed roadmap (50KB, comprehensive)
- [**🎨 Visual Summary**](./MCP_MCPLUSPLUS_VISUAL_SUMMARY.md) - Architecture diagrams (15KB, visual guide)

**Key Features:**
- **Dual-runtime system** with intelligent tool routing
- **Enhanced peer discovery** (GitHub Issues, local file, DHT, mDNS)
- **P2P workflow orchestration** with DAG execution
- **Multi-method bootstrap** (file, environment, public nodes)
- **Auto-cleanup** of stale peers (TTL-based)
- **Zero bridge overhead** with direct Trio execution

**Timeline:** 10-15 weeks (80-120 hours)  
**Status:** Planning Phase - Ready for Implementation

## Features

- **MCP Server**: Full Model Context Protocol server implementation
- **Comprehensive Tools**: Access to all IPFS Datasets functionality as MCP tools (370+ tools, 73 categories)
- **Dual Integration**: Support for both direct IPFS Kit usage and MCP-based integration
- **Enhanced P2P Capabilities** 🆕: Advanced P2P features with MCP++ integration
  - Workflow scheduler for distributed task orchestration
  - Advanced task queue with peer-to-peer execution
  - Peer registry with discovery and management
  - Bootstrap helpers for network initialization
  - Dual-runtime architecture (FastAPI + Trio) for optimal performance
  - Graceful degradation when MCP++ unavailable
- **Configuration Options**: Flexible configuration via command line, YAML files, or Python
- **Python Client**: Easy-to-use Python client for programmatic access

### New P2P Features (Phase 1 Complete) ✅

The MCP server now includes enhanced P2P capabilities through MCP++ integration:

**Import Layer** (5 modules, 20 tests ✅)
- Graceful imports with availability detection
- Workflow scheduler wrapper
- Task queue wrapper
- Peer registry wrapper  
- Bootstrap utilities

**Enhanced Service Manager** (+179 lines)
- Workflow scheduler integration
- Peer registry integration
- Bootstrap capabilities
- Extended state tracking

**Enhanced Registry Adapter** (+231 lines, 19 tests ✅)
- Runtime detection (FastAPI vs Trio)
- Runtime metadata on all tools
- Tool filtering by runtime
- Registration APIs for Trio-native tools

**Integration Testing** (23 tests ✅)
- Service manager integration
- Registry adapter integration
- End-to-end P2P workflows
- Backward compatibility validation
- Error handling

**Total:** 62 tests, 100% passing ✅

## Installation

The MCP server is included in the IPFS Datasets Python package. Make sure you have installed the package:

```bash
pip install ipfs-datasets-py
```

For development installation:

```bash
# Clone the repository
git clone https://github.com/yourusername/ipfs_datasets_py.git
cd ipfs_datasets_py

# Install with development dependencies
pip install -e ".[dev]"

# Run the setup script
./ipfs_datasets_py/mcp_server/setup.sh
```

## Quick Start

Start the server with default settings:

```python
from ipfs_datasets_py.mcp_server import start_server
start_server(host="0.0.0.0", port=8000)
```

Or run the provided start script:

```bash
./ipfs_datasets_py/mcp_server/start_server.sh
```

### Using the Python Client

```python
import asyncio
from ipfs_datasets_py.mcp_server.client import IPFSDatasetsMCPClient

async def main():
    # Connect to the server
    client = IPFSDatasetsMCPClient("http://localhost:8000")
    
    # Load a dataset
    dataset_info = await client.load_dataset("/path/to/dataset.json")
    
    # Process the dataset
    processed_info = await client.process_dataset(
        dataset_info["dataset_id"],
        [
            {"type": "filter", "column": "value", "condition": ">", "value": 50}
        ]
    )
    
    # Save the processed dataset
    await client.save_dataset(
        processed_info["dataset_id"],
        "/path/to/output.csv",
        "csv"
    )

# Run the async function
asyncio.run(main())
```

### Using Enhanced P2P Capabilities 🆕

The MCP server now includes advanced P2P capabilities through MCP++ integration:

```python
from ipfs_datasets_py.mcp_server.p2p_service_manager import P2PServiceManager
from ipfs_datasets_py.mcp_server import mcplusplus

# Check MCP++ availability
caps = mcplusplus.get_capabilities()
print(f"MCP++ available: {caps['mcplusplus_available']}")
print(f"Features: {caps['capabilities']}")

# Create P2P service manager with advanced features
manager = P2PServiceManager(
    enabled=True,
    enable_workflow_scheduler=True,  # Enable workflow scheduler
    enable_peer_registry=True,       # Enable peer discovery
    enable_bootstrap=True,            # Enable bootstrap
    bootstrap_nodes=[                 # Optional custom bootstrap nodes
        "/ip4/104.131.131.82/tcp/4001/p2p/QmaCpDMGvV2BGHeYERUEnRQAwe3N8SzbUtfsmvsqQLuvuJ"
    ]
)

# Check available P2P features
print(f"Capabilities: {manager.get_capabilities()}")
print(f"Has advanced features: {manager.has_advanced_features()}")

# Access workflow scheduler (if available)
scheduler = manager.get_workflow_scheduler()
if scheduler:
    # Workflow scheduler is available
    # Can submit P2P workflows
    pass

# Access peer registry (if available)
registry = manager.get_peer_registry()
if registry:
    # Can discover and connect to peers
    pass
```

**Runtime Detection and Tool Filtering:**

```python
from ipfs_datasets_py.mcp_server.p2p_mcp_registry_adapter import (
    P2PMCPRegistryAdapter,
    RUNTIME_TRIO,
    RUNTIME_FASTAPI
)

# Create adapter
adapter = P2PMCPRegistryAdapter(server)

# Register Trio-native tools
adapter.register_trio_tool("p2p_workflow_submit")
adapter.register_trio_tool("p2p_task_queue")

# Filter tools by runtime
trio_tools = adapter.get_trio_tools()
fastapi_tools = adapter.get_fastapi_tools()

# Get runtime statistics
stats = adapter.get_runtime_stats()
print(f"Total tools: {stats['total_tools']}")
print(f"Trio tools: {stats['trio_tools']}")
print(f"FastAPI tools: {stats['fastapi_tools']}")
```

## Configuration

The server can be configured in several ways:

### Command Line Arguments

```bash
./start_server.sh --host 127.0.0.1 --port 5000 --ipfs-kit-mcp http://localhost:8001 --config /path/to/config.yaml
```

### Configuration File

Create a YAML configuration file:

```yaml
# Server settings
server:
  host: 127.0.0.1
  port: 5000

# IPFS Kit integration
ipfs_kit:
  integration: mcp
  mcp_url: http://localhost:8001

# P2P Configuration (NEW)
p2p:
  enabled: true
  listen_port: 4001
  queue_path: /tmp/p2p_queue
  enable_tools: true
  enable_cache: true
  # MCP++ Advanced Features
  enable_workflow_scheduler: true  # Enable P2P workflow scheduler
  enable_peer_registry: true       # Enable peer discovery
  enable_bootstrap: true            # Enable bootstrap
  bootstrap_nodes:                  # Optional custom bootstrap nodes
    - /ip4/104.131.131.82/tcp/4001/p2p/QmaCpDMGvV2BGHeYERUEnRQAwe3N8SzbUtfsmvsqQLuvuJ
    - /ip4/104.236.179.241/tcp/4001/p2p/QmSoLPppuBtQSGwKDZT2M73ULpjvfd3aZ6ha4oFGL1KrGM
```

### Programmatic Configuration

```python
from ipfs_datasets_py.mcp_server import start_server, configs

# Update configuration
configs.host = "127.0.0.1"
configs.port = 5000
configs.ipfs_kit_integration = "mcp"
configs.ipfs_kit_mcp_url = "http://localhost:8001"

# Start server with updated configs
start_server()
```

## Integration with IPFS Kit Python

The server can integrate with IPFS Kit Python in two ways:

1. **Direct Integration**: Import and use IPFS Kit Python functions directly
2. **MCP Client Integration**: Connect to an existing IPFS Kit Python MCP server

### Direct Integration

This is the default mode. The server will import IPFS Kit Python functions directly.

```yaml
ipfs_kit:
  integration: direct
```

### MCP Client Integration

In this mode, the server will connect to an existing IPFS Kit Python MCP server.

```yaml
ipfs_kit:
  integration: mcp
  mcp_url: http://localhost:8001
```

## Available Tools

The server exposes the following tools:

### Dataset Tools
- `load_dataset`: Load a dataset from a source
- `save_dataset`: Save a dataset to a destination
- `process_dataset`: Process a dataset with transformations
- `convert_dataset_format`: Convert a dataset to a different format

### IPFS Tools
- `pin_to_ipfs`: Pin content to IPFS
- `get_from_ipfs`: Get content from IPFS
- `convert_to_car`: Convert content to a CAR file
- `unixfs_operations`: Perform UnixFS operations on IPFS content

### Vector Tools
- (Vector tools will be documented here)

### Graph Tools
- (Graph tools will be documented here)

### Audit Tools
- (Audit tools will be documented here)

### Security Tools
- (Security tools will be documented here)

### Provenance Tools
- (Provenance tools will be documented here)

## Custom Server Configuration

For advanced use cases, you can create and configure your own server instance:

```python
from ipfs_datasets_py.mcp_server import IPFSDatasetsMCPServer
import asyncio

async def run_custom_server():
    # Create server instance
    server = IPFSDatasetsMCPServer()
    
    # Register tools
    server.register_tools()
    
    # Register IPFS Kit tools
    server.register_ipfs_kit_tools(ipfs_kit_mcp_url="http://localhost:8001")
    
    # Start server
    await server.start(host="127.0.0.1", port=5000)

# Run custom server
asyncio.run(run_custom_server())
```
