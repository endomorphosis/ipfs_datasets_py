# IPFS Datasets MCP Server

This package provides a Model Context Protocol (MCP) server implementation for IPFS Datasets Python, enabling AI models like Claude to interact with IPFS datasets through standardized tools.

---

## 🎯 Current Status (2026-02-25)

**Progress:** ✅ **100% COMPLETE** — All 7 refactoring phases done + MCP++ spec alignment  
**Test Coverage:** 85-90% (1,570+ passing tests across MCP++ sessions through v39)  
**Security:** ✅ All 5 critical vulnerabilities fixed  
**Architecture:** ✅ Thin wrappers, hierarchical tools, dual-runtime, lazy loading, MCP++ integration  
**Code Quality:** ✅ 0 bare exceptions · 0 missing docstrings · 0 missing return types  
**Tools:** ✅ 51 categories · 292 tool files · ~407 callable tool functions

---

### 📚 Documentation Quick Guide

### 🚀 **For New Contributors** → Start Here!
- **[QUICKSTART.md](QUICKSTART.md)** — Get the server running in minutes
- **[THIN_TOOL_ARCHITECTURE.md](THIN_TOOL_ARCHITECTURE.md)** — Core architecture principles

### 📊 **Status & History**
- **[PHASES_STATUS.md](PHASES_STATUS.md)** — All 7 phases complete with metrics
- **[CHANGELOG.md](CHANGELOG.md)** — Full change history

### 🏗️ **Architecture**
- **[THIN_TOOL_ARCHITECTURE.md](THIN_TOOL_ARCHITECTURE.md)** — Thin wrapper pattern, core principles
- **[docs/architecture/](docs/architecture/)** — Dual-runtime design, MCP++ alignment, ADRs

### 🔒 **Security**
- **[SECURITY.md](SECURITY.md)** — Security posture, fixes applied, practices

### 📋 **Historical Docs** (Reference Only)
- **[ARCHIVE/](ARCHIVE/)** — Archived historical planning documents

---

## ✅ All 7 Phases + MCP++ Alignment Complete

| Phase | Status | Key Achievement |
|-------|--------|-----------------|
| **Phase 1: Security** | ✅ 100% | 5 vulnerabilities fixed |
| **Phase 2: Architecture** | ✅ 100% | HierarchicalToolManager, thin wrappers, dual-runtime |
| **Phase 3: Testing** | ✅ 100% | 1,570+ tests passing, 0 failures |
| **Phase 4: Code Quality** | ✅ 100% | 0 bare exceptions, 0 missing types/docstrings |
| **Phase 5: Thick Tool Refactoring** | ✅ 100% | 15 thick files extracted (avg 70% reduction) |
| **Phase 6: Consolidation** | ✅ 100% | 28 stale docs archived, 7 authoritative kept |
| **Phase 7: Performance** | ✅ 100% | Lazy loading, schema caching, P2P connection pool |
| **Phase M/N: anyio migration** | ✅ 100% | anyio-first, Flask deprecated, no-asyncio CI |
| **Phase P: MCP++ Alignment** | ✅ 100% | UCAN delegation, event DAG, P2P transport, compliance (v1–v39) |

**See:** [PHASES_STATUS.md](PHASES_STATUS.md) for detailed metrics.

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
- **51 tool categories** with **292 tool files** (~407 callable functions)
- **4 meta-tools** expose all functionality
- Dynamic loading, lazy initialization
- CLI-style tool naming (category/operation)

**P2P Integration (MCP++):**
- UCAN delegation, event DAG provenance, P2P transport bindings
- Workflow scheduler, task queue, peer registry
- 50-70% latency reduction for P2P operations
- Graceful degradation when unavailable
- Native Trio integration
- Compliance checker, policy audit log, NL UCAN policy compiler

**Configuration & Monitoring:**
- `server_context.py` - Server state management
- `validators.py` - Input validation
- `monitoring.py` - Metrics and observability

### Architecture Patterns

**1. Hierarchical Tools (99% context reduction)**
```python
# Instead of 407 tool functions, expose only 4 meta-tools:
mcp.add_tool(tools_list_categories)  # List all 51 categories
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
- **1,570+ test functions** passing (MCP++ sessions v1–v39), 0 failing
- **Test coverage:** 85-90% across core modules

### Test Structure
```
tests/mcp/
├── unit/              # Component unit tests (179 files)
│   ├── test_server_core.py (40 tests)
│   ├── test_hierarchical_tool_manager.py (26 tests)
│   ├── test_fastapi_service.py (19 tests)
│   ├── test_trio_runtime.py (20 tests)
│   ├── test_validators.py (15 tests)
│   ├── test_monitoring.py, test_monitoring_session39.py
│   ├── test_exceptions.py (12 tests)
│   ├── test_p2p_service_manager.py (15 tests)
│   ├── test_tool_registry.py, test_tool_registry_session39.py
│   ├── test_mcplusplus_v*.py (39 MCP++ spec session files)
│   └── [100+ more unit test files covering all 51 tool categories]
├── integration/       # Integration tests (9 files)
│   ├── test_exception_integration.py (15 tests)
│   ├── test_p2p_integration.py (6 tests)
│   └── [7 more integration test files]
├── e2e/               # End-to-end tests
│   └── test_full_tool_lifecycle.py (10 tests)
└── [scripts, performance tests]
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
1. Read [QUICKSTART.md](QUICKSTART.md) — server setup and running tests
2. Read [THIN_TOOL_ARCHITECTURE.md](THIN_TOOL_ARCHITECTURE.md) — core architecture
3. Check [MASTER_IMPROVEMENT_PLAN_2026_v5.md](MASTER_IMPROVEMENT_PLAN_2026_v5.md) for open tasks
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

### Overall Status: 100% Complete ✅

```
Phase 1: Security          ████████████████████████ 100% ✅
Phase 2: Architecture      ████████████████████████ 100% ✅
Phase 3: Testing           ████████████████████████ 100% ✅
Phase 4: Quality           ████████████████████████ 100% ✅
Phase 5: Tool Cleanup      ████████████████████████ 100% ✅
Phase 6: Consolidation     ████████████████████████ 100% ✅
Phase 7: Performance       ████████████████████████ 100% ✅
Phase M/N: anyio migration ████████████████████████ 100% ✅
Phase P: MCP++ Alignment   ████████████████████████ 100% ✅ (v1–v39)
```

**See:** [PHASES_STATUS.md](PHASES_STATUS.md) for full per-phase metrics.

---

## 📞 Support & Resources

### Documentation
- **Architecture:** [THIN_TOOL_ARCHITECTURE.md](THIN_TOOL_ARCHITECTURE.md)
- **Security:** [SECURITY.md](SECURITY.md)
- **API Reference:** [docs/api/tool-reference.md](docs/api/tool-reference.md)
- **Development:** [docs/development/](docs/development/)

### Key Metrics
- **Test Functions:** 1,570+ passing, 0 failing
- **Test Coverage:** 85-90%
- **Tool Categories:** 51 categories · 292 tool files · ~407 callable functions
- **Context Reduction:** 99% (407 functions → 4 meta-tools)
- **Thin Wrapper Compliance:** 99%+

---

## 🎯 Improvement Areas

1. Coverage improvements: `monitoring.py` → 85%+, `enterprise_api.py` → 80%+
2. Extend `docs/api/tool-reference.md` to cover all 51 categories
3. Migrate `legacy_mcp_tools/` to appropriate category directories
4. Clean up `lizardperson_argparse_programs/` empty placeholder files

---

**Version:** 6.0  
**Last Updated:** 2026-02-25  
**Status:** ✅ Production Ready — All phases complete, MCP++ v1–v39 alignment done

## Features

- **MCP Server**: Full Model Context Protocol server implementation
- **Comprehensive Tools**: Access to all IPFS Datasets functionality as MCP tools (~407 functions, 51 categories)
- **Dual Integration**: Support for both direct IPFS Kit usage and MCP-based integration
- **Enhanced P2P Capabilities** ✅: Advanced P2P features with MCP++ integration
  - Workflow scheduler for distributed task orchestration
  - Advanced task queue with peer-to-peer execution
  - Peer registry with discovery and management
  - UCAN delegation, event DAG provenance, P2P transport bindings
  - Compliance checker, policy audit log, NL UCAN policy compiler
  - Dual-runtime architecture (FastAPI + Trio) for optimal performance
  - Graceful degradation when MCP++ unavailable
- **Configuration Options**: Flexible configuration via command line, YAML files, or Python
- **Python Client**: Easy-to-use Python client for programmatic access

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
import anyio
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

# Run the async function (anyio works with both asyncio and trio backends)
anyio.run(main)
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

The server exposes ~407 callable tool functions across 51 categories. Use the hierarchical meta-tools
to discover and call them at runtime, or see [docs/api/tool-reference.md](docs/api/tool-reference.md)
for the full reference.

### Core Tool Categories

| Category | Functions | Description |
|----------|-----------|-------------|
| `dataset_tools` | 6 | Load, save, convert, process datasets; text-to-FOL, legal-to-deontic |
| `graph_tools` | 19 | Knowledge graphs: Cypher/GraphQL, visualization, KG completion, explainability |
| `logic_tools` | 27 | FOL, TDFOL, CEC/DCEC theorem proving, deontic and temporal reasoning |
| `pdf_tools` | 8 | PDF GraphRAG, OCR, entity extraction, cross-document analysis |
| `media_tools` | 17 | FFmpeg convert/mux/stream/edit/batch, yt-dlp download |
| `web_archive_tools` | 59 | Common Crawl, Wayback Machine, Brave/Google/GitHub/HuggingFace search |
| `legal_dataset_tools` | 50 | US Code, Federal Register, RECAP, CourtListener, municipal codes |
| `embedding_tools` | 2 | Embedding generation and batching |
| `ipfs_tools` | 2 | IPFS pin and get |
| `vector_tools` | 2 | Vector index creation and search |
| `storage_tools` | 9 | Multi-backend storage management |
| `workflow_tools` | 17 | DAG workflow orchestration, scheduling, batch processing |

See [tools/README.md](tools/README.md) for the full 51-category listing.

## Custom Server Configuration

For advanced use cases, you can create and configure your own server instance:

```python
import anyio
from ipfs_datasets_py.mcp_server import IPFSDatasetsMCPServer

async def run_custom_server():
    # Create server instance
    server = IPFSDatasetsMCPServer()
    
    # Register tools
    server.register_tools()
    
    # Register IPFS Kit tools
    server.register_ipfs_kit_tools(ipfs_kit_mcp_url="http://localhost:8001")
    
    # Start server
    await server.start(host="127.0.0.1", port=5000)

# Run custom server (anyio works with both asyncio and trio backends)
anyio.run(run_custom_server)
```
