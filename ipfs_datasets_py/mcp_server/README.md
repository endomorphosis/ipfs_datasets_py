# IPFS Datasets MCP Server

A [Model Context Protocol (MCP)](https://modelcontextprotocol.io/) server that exposes the full IPFS Datasets Python library as callable tools for AI assistants such as Claude, Cursor, and any other MCP-compatible client.

**~407 functions · 51 tool categories · dual-runtime (FastAPI + Trio) · 1,570+ tests**

---

## Table of Contents

1. [Features](#features)
2. [Installation](#installation)
3. [Quick Start](#quick-start)
4. [Connecting to an AI Client](#connecting-to-an-ai-client)
5. [Tool Categories](#tool-categories)
6. [Architecture](#architecture)
7. [Configuration](#configuration)
8. [Python Client Usage](#python-client-usage)
9. [P2P Capabilities](#p2p-capabilities)
10. [Testing](#testing)
11. [Contributing](#contributing)
12. [Documentation](#documentation)

---

## Features

- **Comprehensive tool coverage** — ~407 callable functions across 51 categories covering datasets, knowledge graphs, logic/theorem proving, PDF processing, media, legal data, web archiving, embeddings, IPFS, vector stores, and more.
- **Hierarchical tool discovery** — 4 meta-tools (`list_categories`, `list_tools`, `get_schema`, `dispatch`) let clients browse and invoke the full catalog without loading every tool definition upfront.
- **Dual-runtime architecture** — FastAPI for general tools; Trio for latency-sensitive P2P operations (50–70 % faster for P2P calls).
- **Graceful degradation** — optional P2P/MCP++ features fall back cleanly when the underlying dependencies are unavailable.
- **UCAN delegation & compliance** — built-in support for decentralized authorization (UCAN), event-DAG provenance, policy audit logs, and a natural-language UCAN policy compiler.
- **Production-grade** — strict typing, full docstrings, 85–90 % test coverage, zero bare exception handlers.

---

## Installation

The MCP server is part of the `ipfs-datasets-py` package:

```bash
pip install ipfs-datasets-py
```

For development (editable install with all extras):

```bash
git clone https://github.com/endomorphosis/ipfs_datasets_py.git
cd ipfs_datasets_py
pip install -e ".[dev]"
```

---

## Quick Start

### Start with the default stdio transport (for AI clients)

```bash
python -m ipfs_datasets_py.mcp_server
```

### Start as a standalone HTTP server

```bash
python ipfs_datasets_py/mcp_server/standalone_server.py
# or the lightweight variant:
python ipfs_datasets_py/mcp_server/simple_server.py
```

### Start via Python

```python
from ipfs_datasets_py.mcp_server import start_server

start_server(host="127.0.0.1", port=5000)
```

---

## Connecting to an AI Client

### Claude Desktop (`claude_desktop_config.json`)

```json
{
  "mcpServers": {
    "ipfs-datasets": {
      "command": "python",
      "args": ["-m", "ipfs_datasets_py.mcp_server"]
    }
  }
}
```

### Cursor / VS Code (MCP extension)

Point the extension at `python -m ipfs_datasets_py.mcp_server` using the `stdio` transport.

### Programmatic MCP client

```python
import anyio
from ipfs_datasets_py.mcp_server.client import IPFSDatasetsMCPClient

async def main():
    client = IPFSDatasetsMCPClient("http://localhost:5000")

    # Load a Hugging Face dataset
    info = await client.load_dataset("squad")
    print(info)

anyio.run(main)
```

---

## Tool Categories

Tools are organized into 51 categories. Use the hierarchical meta-tools to browse them at runtime:

```python
# Inside an MCP session (or via tools_dispatch):

# 1. List all categories
categories = tools_list_categories()
# → ['admin_tools', 'alert_tools', 'dataset_tools', 'graph_tools', ...]

# 2. List tools in a category
tools = tools_list_tools("dataset_tools")
# → ['load_dataset', 'save_dataset', 'convert_dataset', ...]

# 3. Inspect a tool's schema
schema = tools_get_schema("dataset_tools", "load_dataset")
# → {parameters: {source: {type: "string", description: "..."}, ...}, ...}

# 4. Call any tool
result = tools_dispatch("dataset_tools", "load_dataset", {"source": "squad"})
```

### Category summary

| Category | Tool files | Description |
|---|---|---|
| `admin_tools` | 2 | Server administration, config reload |
| `alert_tools` | 1 | Alert dispatch and routing |
| `analysis_tools` | 1 | Data analysis helpers |
| `audit_tools` | 3 | Security audit, compliance reporting |
| `auth_tools` | 2 | Authentication, token management |
| `background_task_tools` | 3 | Async task submission and status |
| `bespoke_tools` | 7 | System health, cache stats, index management, workflow execution |
| `cache_tools` | 2 | Cache inspection and invalidation |
| `dashboard_tools` | 3 | Metrics dashboards |
| `data_processing_tools` | 1 | General data transformation |
| `dataset_tools` | 7 | Load, save, convert, and process datasets (HuggingFace, CSV, JSON, Parquet, Arrow) |
| `development_tools` | 19 | Code generation, debugging, scaffolding |
| `discord_tools` | 4 | Discord server/channel export and analysis |
| `email_tools` | 3 | IMAP folder export, EML parsing, email analysis |
| `embedding_tools` | 9 | Vector embedding generation, batching, similarity |
| `file_converter_tools` | 8 | Format conversion (CSV, JSON, Parquet, etc.) |
| `file_detection_tools` | 3 | MIME type and encoding detection |
| `finance_data_tools` | 8 | Financial market data and indicators |
| `geospatial_tools` | 1 | Geospatial queries and processing |
| `graph_tools` | 19 | Knowledge graphs: Cypher, GraphQL, visualization, GNN embeddings, ZK proofs, federated queries, link prediction |
| `index_management_tools` | 1 | Index creation and deletion |
| `investigation_tools` | 7 | Data investigation and lineage tracing |
| `ipfs_cluster_tools` | 1 | IPFS Cluster pinning |
| `ipfs_tools` | 3 | IPFS add, pin, get, cat |
| `legal_dataset_tools` | 38 | US Code, Federal Register, PACER/RECAP, CourtListener, municipal codes |
| `logic_tools` | 16 | FOL, TDFOL, CEC/DCEC theorem proving, deontic and temporal reasoning |
| `mcplusplus` | 3 | MCP++ UCAN, event-DAG, and P2P transport primitives |
| `media_tools` | 9 | FFmpeg encode/mux/stream/batch, yt-dlp download from 1,000+ platforms |
| `medical_research_scrapers` | 6 | PubMed, ClinicalTrials, bioRxiv scrapers |
| `monitoring_tools` | 3 | Server metrics, health checks, alert rules |
| `p2p_tools` | 2 | Peer discovery, connection management |
| `p2p_workflow_tools` | 1 | Distributed workflow submission |
| `pdf_tools` | 8 | PDF GraphRAG, OCR, entity extraction, cross-document analysis |
| `provenance_tools` | 2 | Data lineage and provenance tracking |
| `rate_limiting_tools` | 1 | Rate limit inspection and configuration |
| `search_tools` | 1 | Full-text and semantic search |
| `security_tools` | 1 | Secrets scanning, vulnerability checks |
| `session_tools` | 3 | Session management |
| `software_engineering_tools` | 11 | Repo analysis, PR review, code search |
| `sparse_embedding_tools` | 1 | Sparse/BM25 embeddings |
| `storage_tools` | 2 | Multi-backend storage (S3, GCS, local) |
| `vector_store_tools` | 3 | FAISS / Qdrant / Elasticsearch index management |
| `vector_tools` | 6 | Vector index creation, insertion, search |
| `web_archive_tools` | 19 | Common Crawl, Wayback Machine, search APIs (Brave, Google, GitHub, HuggingFace) |
| `web_scraping_tools` | 1 | Generic web scraping |
| `workflow_tools` | 2 | DAG workflow definition and execution |

See [docs/api/tool-reference.md](docs/api/tool-reference.md) for the full API reference with parameters and return shapes.

---

## Architecture

```
AI Client (Claude / Cursor / …)
         │  MCP protocol (stdio or HTTP)
         ▼
    server.py  (FastMCP)
         │
         ▼
HierarchicalToolManager        ← 4 meta-tools expose all 51 categories lazily
         │
         ▼
   RuntimeRouter               ← dispatches to the correct async runtime
   ├── FastAPI runtime  ──────→ general tools
   └── Trio runtime     ──────→ P2P / latency-sensitive tools
```

### Key source files

| File | Purpose |
|---|---|
| `server.py` | Main MCP server (FastMCP) |
| `hierarchical_tool_manager.py` | Lazy tool loading, meta-tool dispatch |
| `fastapi_service.py` | REST API / FastAPI runtime |
| `runtime_router.py` | Dual-runtime dispatch logic |
| `trio_adapter.py` / `trio_bridge.py` | Trio integration for P2P tools |
| `configs.py` | Server configuration (dataclass + YAML) |
| `monitoring.py` | Metrics collection and observability |
| `validators.py` | Input validation helpers |
| `exceptions.py` | Typed exception hierarchy |
| `client.py` | Python async client |
| `enterprise_api.py` | Enterprise REST API endpoints |
| `ucan_delegation.py` | UCAN delegation manager |
| `compliance_checker.py` | Compliance rule evaluation |
| `event_dag.py` | Event-DAG provenance |
| `p2p_service_manager.py` | P2P service lifecycle |

### Design principles

**Thin wrapper pattern** — each tool file (<150 lines) delegates all business logic to a core module so tools stay testable in isolation:

```python
# tools/dataset_tools/load_dataset.py  (thin MCP wrapper)
@tool_metadata(runtime="fastapi")
async def load_dataset(source: str, split: str = "train") -> dict:
    """Load a dataset from a local path or HuggingFace hub."""
    loader = DatasetLoader()            # business logic lives here
    return await loader.load(source, split=split)
```

**Hierarchical discovery** — instead of registering ~407 individual tool functions with the MCP server (which exhausts context windows), only 4 meta-tools are registered; everything else is discovered on demand:

```python
mcp.add_tool(tools_list_categories)   # list 51 category names
mcp.add_tool(tools_list_tools)        # list tools within a category
mcp.add_tool(tools_get_schema)        # get parameter schema for a tool
mcp.add_tool(tools_dispatch)          # execute any tool by name
```

**Graceful degradation** — optional heavy dependencies (Trio, libp2p, GPU libraries) are imported lazily with clean fallbacks so the server starts successfully in minimal environments.

---

## Configuration

Configuration is loaded from (in priority order): programmatic overrides → YAML file → environment variables → defaults.

### YAML configuration file

```yaml
# server settings
host: 127.0.0.1
port: 5000
transport: stdio        # "stdio" for AI clients, "http" for REST

# IPFS Kit integration
ipfs_kit:
  integration: direct   # "direct" (import) or "mcp" (proxy to another server)
  mcp_url: http://localhost:8001   # only needed when integration: mcp

# P2P / MCP++ settings
p2p:
  enabled: true
  listen_port: 4001
  enable_workflow_scheduler: true
  enable_peer_registry: true
  bootstrap_nodes:
    - /ip4/104.131.131.82/tcp/4001/p2p/QmaCpDMGvV2BGHeYERUEnRQAwe3N8SzbUtfsmvsqQLuvuJ
```

### Command-line arguments

```bash
python -m ipfs_datasets_py.mcp_server \
    --host 127.0.0.1 \
    --port 5000 \
    --config /path/to/config.yaml
```

### Programmatic configuration

```python
from ipfs_datasets_py.mcp_server import configs, start_server

configs.host = "0.0.0.0"
configs.port = 8080
start_server()
```

---

## Python Client Usage

```python
import anyio
from ipfs_datasets_py.mcp_server.client import IPFSDatasetsMCPClient

async def main():
    client = IPFSDatasetsMCPClient("http://localhost:5000")

    # Load a dataset
    dataset_info = await client.load_dataset("/path/to/data.json")

    # Apply transformations
    processed = await client.process_dataset(
        dataset_info["dataset_id"],
        [{"type": "filter", "column": "score", "condition": ">", "value": 0.5}],
    )

    # Save result
    await client.save_dataset(processed["dataset_id"], "/output/data.csv", "csv")

anyio.run(main)
```

---

## P2P Capabilities

The server supports optional peer-to-peer features via the MCP++ layer:

```python
from ipfs_datasets_py.mcp_server.p2p_service_manager import P2PServiceManager

manager = P2PServiceManager(
    enabled=True,
    enable_workflow_scheduler=True,
    enable_peer_registry=True,
    bootstrap_nodes=[
        "/ip4/104.131.131.82/tcp/4001/p2p/QmaCpDMGvV2BGHeYERUEnRQAwe3N8SzbUtfsmvsqQLuvuJ"
    ],
)

print(manager.get_capabilities())   # inspect what is available

scheduler = manager.get_workflow_scheduler()   # None if unavailable
registry  = manager.get_peer_registry()        # None if unavailable
```

P2P features degrade gracefully: if `ipfs_accelerate_py` or Trio are not installed, the server still starts and all non-P2P tools work normally.

---

## Testing

```bash
# Run the full MCP test suite
pytest tests/mcp/ -v

# Run with coverage report
pytest tests/mcp/ --cov=ipfs_datasets_py.mcp_server --cov-report=html

# Run a specific component
pytest tests/mcp/unit/test_server_core.py -v

# Fast unit tests only
pytest tests/mcp/unit/ -v
```

Test layout:

```
tests/mcp/
├── unit/          # ~180 files, 1,400+ test functions
├── integration/   # 9 files, cross-component tests
├── e2e/           # end-to-end lifecycle tests
└── performance/   # benchmarks
```

---

## Contributing

1. Read [QUICKSTART.md](QUICKSTART.md) — setup and running tests.
2. Read [THIN_TOOL_ARCHITECTURE.md](THIN_TOOL_ARCHITECTURE.md) — the thin-wrapper pattern.
3. Add tests following the GIVEN-WHEN-THEN pattern used throughout `tests/mcp/`.
4. Keep functions under 100 lines, add type hints and docstrings, avoid bare `except` clauses.
5. Run the checks below before opening a PR.

```bash
pytest tests/mcp/ -v
mypy ipfs_datasets_py/mcp_server/
flake8 ipfs_datasets_py/mcp_server/
```

---

## Documentation

| Document | Description |
|---|---|
| [QUICKSTART.md](QUICKSTART.md) | Get the server running in minutes |
| [THIN_TOOL_ARCHITECTURE.md](THIN_TOOL_ARCHITECTURE.md) | Thin-wrapper design, architecture principles |
| [SECURITY.md](SECURITY.md) | Security posture and hardening notes |
| [CHANGELOG.md](CHANGELOG.md) | Version history |
| [docs/api/tool-reference.md](docs/api/tool-reference.md) | Full API reference — all 51 categories |
| [docs/architecture/](docs/architecture/) | Dual-runtime design, MCP++ alignment, ADRs |
| [docs/guides/cookbook.md](docs/guides/cookbook.md) | Usage recipes (parallel dispatch, streaming, etc.) |
| [docs/guides/p2p-migration.md](docs/guides/p2p-migration.md) | Migrating to P2P infrastructure |
| [docs/development/tool-patterns.md](docs/development/tool-patterns.md) | How to write a new tool |
