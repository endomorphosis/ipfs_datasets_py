# IPFS Datasets MCP Server

A [Model Context Protocol (MCP)](https://modelcontextprotocol.io/) server that exposes the full IPFS Datasets Python library as callable tools for AI assistants such as Claude, Cursor, and any other MCP-compatible client.

**~407 functions · 51 tool categories · dual-runtime (FastAPI + Trio) · 1,570+ tests**

---

## Table of Contents

1. [Features](#features)
2. [Installation](#installation)
3. [Quick Start](#quick-start)
4. [Connecting to an AI Client](#connecting-to-an-ai-client)
5. [How the Server Works](#how-the-server-works)
6. [Tool Categories](#tool-categories)
7. [Architecture](#architecture)
8. [Dispatch Pipeline](#dispatch-pipeline)
9. [Authorization & Compliance (MCP++)](#authorization--compliance-mcp)
10. [Configuration](#configuration)
11. [Python Client Usage](#python-client-usage)
12. [P2P Capabilities](#p2p-capabilities)
13. [Error Handling](#error-handling)
14. [Testing](#testing)
15. [Contributing](#contributing)
16. [Documentation](#documentation)

---

## Features

- **Comprehensive tool coverage** — ~407 callable functions across 51 categories: datasets, knowledge graphs, logic/theorem proving, PDF processing, media, legal data, web archiving, embeddings, IPFS, vector stores, workflows, and more.
- **Hierarchical tool discovery** — 4 meta-tools (`tools_list_categories`, `tools_list_tools`, `tools_get_schema`, `tools_dispatch`) let AI clients browse and invoke the full catalog without loading every tool definition upfront, reducing context-window usage by ~99%.
- **Dual-runtime architecture** — FastAPI for general tools (asyncio); Trio for latency-sensitive P2P operations (50–70% faster for P2P calls). All tools are written as `async def` using `anyio` so they work in either runtime.
- **MCP++ dispatch pipeline** — every tool invocation passes through staged compliance, risk scoring, UCAN delegation, and NL policy gates before execution.
- **UCAN delegation & compliance** — decentralized capability-based authorization (UCAN), event-DAG provenance, policy audit logs, and a natural-language UCAN policy compiler.
- **Circuit breaker** — built-in circuit breaker on the `HierarchicalToolManager` protects against cascading failures during tool dispatch.
- **Production-grade** — typed exception hierarchy, comprehensive input validation, 85–90% test coverage, zero bare exception handlers.

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
    info = await client.load_dataset("squad")
    print(info)

anyio.run(main)
```

---

## How the Server Works

### Startup lifecycle

Server startup is managed by `ServerContext` (`server_context.py`), which initialises and tears down all shared resources in a defined order:

```python
from ipfs_datasets_py.mcp_server.server_context import create_server_context

with create_server_context() as ctx:
    tool_manager   = ctx.tool_manager        # HierarchicalToolManager
    metadata_reg   = ctx.metadata_registry   # ToolMetadataRegistry
    p2p_services   = ctx.p2p_services        # P2PServiceManager (if enabled)
    scheduler      = ctx.workflow_scheduler  # WorkflowScheduler (if enabled)
```

`ServerContext` also accepts cleanup handlers registered at runtime, ensuring every resource (vector stores, workflow schedulers, P2P connections) is properly released on shutdown even when exceptions occur.

### Tool registration

`server.py` uses FastMCP and registers **only 4 meta-tools** at startup:

```python
mcp.add_tool(tools_list_categories)   # list all 51 category names
mcp.add_tool(tools_list_tools)        # list tools within a category
mcp.add_tool(tools_get_schema)        # get parameter schema for a tool
mcp.add_tool(tools_dispatch)          # execute any tool by name
```

Tool modules within the 51 category directories are **lazily imported** the first time a call arrives for that category. This keeps startup time fast and avoids loading heavy dependencies (torch, FFmpeg bindings, etc.) until they are actually needed.

### Tool lookup flow

```
tools_dispatch("graph_tools", "graph_create", {"name": "myKG"})
         │
         ▼
HierarchicalToolManager.dispatch()
  1. Resolve category directory (tools/graph_tools/)
  2. Import category __init__.py (lazy, cached)
  3. Look up function by name in the module's __all__
  4. Validate parameters via EnhancedParameterValidator
  5. Route to correct async runtime (FastAPI or Trio)
  6. Execute with circuit-breaker protection
  7. Return result dict
```

---

## Tool Categories

### Hierarchical meta-tools (use these inside an MCP session)

```python
# 1. List all categories
categories = tools_list_categories()
# → ['admin_tools', 'alert_tools', 'dataset_tools', 'graph_tools', ...]

# 2. List tools in a category
tools = tools_list_tools("graph_tools")
# → ['graph_create', 'graph_add_entity', 'graph_add_relationship', ...]

# 3. Inspect a tool's parameter schema
schema = tools_get_schema("graph_tools", "graph_create")
# → {name: {type: "string", required: true, description: "..."}, ...}

# 4. Execute any tool
result = tools_dispatch("dataset_tools", "load_dataset", {"source": "squad"})
```

### Category reference

| Category | Tool files | Exported functions (sample) |
|---|---|---|
| `dataset_tools` | 7 | `load_dataset`, `save_dataset`, `process_dataset`, `convert_dataset_format`, `text_to_fol`, `legal_text_to_deontic` |
| `graph_tools` | 19 | `graph_create`, `graph_add_entity`, `graph_add_relationship`, `graph_query_cypher`, `graph_search_hybrid`, `graph_graphql_query`, `graph_visualize`, `graph_complete_suggestions`, `graph_explain`, `graph_provenance_verify`, `graph_srl_extract`, `graph_ontology_materialize`, `graph_distributed_execute`, `graph_transaction_begin/commit/rollback` |
| `logic_tools` | 16 | `tdfol_prove`, `tdfol_batch_prove`, `tdfol_parse`, `tdfol_convert`, `tdfol_kb_add_axiom`, `tdfol_kb_add_theorem`, `tdfol_kb_query`, `tdfol_kb_export`, `tdfol_visualize`, `cec_prove`, `cec_check_theorem`, `cec_parse`, `cec_validate_formula`, `cec_list_rules`, `cec_apply_rule`, `cec_analyze_formula`, `cec_formula_complexity`, `logic_capabilities`, `logic_health`, `logic_build_knowledge_graph`, `logic_verify_rag_output`, `check_document_consistency`, `query_theorems`, `add_theorem`, `bulk_process_caselaw` |
| `pdf_tools` | 8 | `pdf_analyze_relationships`, `pdf_batch_process`, `pdf_cross_document_analysis`, `pdf_extract_entities`, `pdf_graphrag_process`, `pdf_ocr_process`, `pdf_decompose`, `pdf_semantic_search` |
| `media_tools` | 9 | `ffmpeg_convert`, `ffmpeg_mux`, `ffmpeg_demux`, `ffmpeg_stream`, `ffmpeg_batch`, `ffmpeg_edit`, `ffmpeg_filters`, `ytdlp_download`, `ytdlp_list_formats` |
| `embedding_tools` | 9 | `generate_embedding`, `generate_batch_embeddings`, `generate_embeddings_from_file`, `get_available_tools`, `shard_embeddings`, `advanced_embedding_generation`, `advanced_search`, `cluster_management` |
| `web_archive_tools` | 19 | `brave_search`, `common_crawl_search`, `wayback_machine_fetch`, `github_search`, `huggingface_search`, `google_search`, `archive_is_fetch`, `autoscraper_scrape` |
| `legal_dataset_tools` | 38 | US Code, Federal Register, PACER/RECAP, CourtListener, municipal codes, `brave_legal_search`, `bluebook_citation_validator`, `citation_extraction` |
| `ipfs_tools` | 3 | `pin_to_ipfs`, `get_from_ipfs`, IPFS add/cat |
| `vector_tools` | 6 | `create_vector_index`, `search_vector_index`, `vector_store_management`, shared state helpers |
| `storage_tools` | 2 | `store_data`, `retrieve_data`, `list_stored_items`, `delete_stored_item`, `get_storage_stats` |
| `workflow_tools` | 2 | `run_workflow`, `schedule_workflow`, DAG orchestration |
| `p2p_tools` | 2 | `p2p_status`, `list_peers`, `workflow_scheduler` |
| `audit_tools` | 3 | `record_audit_event`, `generate_audit_report` |
| `auth_tools` | 2 | Authentication, token management |
| `monitoring_tools` | 3 | `get_system_metrics`, `health_check`, `set_alert_rule` |
| `admin_tools` | 2 | Server administration, config reload |
| `alert_tools` | 1 | Alert dispatch and routing |
| `analysis_tools` | 1 | Data analysis helpers |
| `background_task_tools` | 3 | Async task submission and status |
| `bespoke_tools` | 7 | System health, cache stats, index management, workflow execution |
| `cache_tools` | 2 | Cache inspection and invalidation |
| `dashboard_tools` | 3 | Metrics dashboards |
| `data_processing_tools` | 1 | General data transformation |
| `development_tools` | 19 | `test_generator`, `documentation_generator`, `linting_tools`, code analysis, debugging, scaffolding |
| `discord_tools` | 4 | Discord server/channel export and analysis |
| `email_tools` | 3 | IMAP folder export, EML parsing, email analysis |
| `file_converter_tools` | 8 | Format conversion (CSV, JSON, Parquet, Arrow, etc.) |
| `file_detection_tools` | 3 | MIME type and encoding detection |
| `finance_data_tools` | 8 | Financial market data and indicators |
| `geospatial_tools` | 1 | Geospatial queries and processing |
| `index_management_tools` | 1 | Index creation and deletion |
| `investigation_tools` | 7 | Data investigation and lineage tracing |
| `ipfs_cluster_tools` | 1 | IPFS Cluster pinning |
| `mcplusplus` | 3 | MCP++ UCAN, event-DAG, and P2P transport primitives |
| `medical_research_scrapers` | 6 | PubMed, ClinicalTrials, bioRxiv scrapers |
| `provenance_tools` | 2 | Data lineage and provenance tracking |
| `rate_limiting_tools` | 1 | Rate limit inspection and configuration |
| `search_tools` | 1 | Full-text and semantic search |
| `security_tools` | 1 | Secrets scanning, vulnerability checks |
| `session_tools` | 3 | Session management |
| `software_engineering_tools` | 11 | Repo analysis, PR review, code search |
| `sparse_embedding_tools` | 1 | Sparse/BM25 embeddings |
| `vector_store_tools` | 3 | FAISS / Qdrant / Elasticsearch index management |
| `web_scraping_tools` | 1 | Generic web scraping |

See [docs/api/tool-reference.md](docs/api/tool-reference.md) for the full API reference with parameters and return shapes.

---

## Architecture

```
AI Client (Claude / Cursor / …)
         │  MCP protocol (stdio or HTTP)
         ▼
    server.py  (FastMCP)
         │  registers 4 meta-tools
         ▼
HierarchicalToolManager       ← lazy category loading, circuit-breaker
         │
         ▼
   RuntimeRouter              ← reads @tool_metadata(runtime=…) annotation
   ├── FastAPI runtime ──────→ general tools (~380 functions, asyncio)
   └── Trio runtime    ──────→ P2P tools (~26 functions, structured concurrency)
         │
         ▼
  DispatchPipeline            ← MCP++ gate sequence (see next section)
         │
         ▼
   Tool function              ← thin wrapper → delegates to core engine
```

### Key source files

| File | Purpose |
|---|---|
| `server.py` | Main MCP server entry point (FastMCP); registers meta-tools, starts runtimes |
| `server_context.py` | `ServerContext` — lifecycle manager for all shared resources |
| `hierarchical_tool_manager.py` | Lazy tool loading, meta-tool implementations, circuit breaker |
| `tool_metadata.py` | `@tool_metadata` decorator, `ToolMetadataRegistry`, runtime annotations |
| `tool_registry.py` | `ClaudeMCPTool` wrapper, `execute()`, `get_schema()`, usage stats |
| `runtime_router.py` | `RuntimeRouter` — dual-runtime dispatch, per-tool latency metrics |
| `dispatch_pipeline.py` | `DispatchPipeline` — staged compliance/risk/delegation/policy gates |
| `fastapi_service.py` | REST API / FastAPI runtime (JWT auth, rate limiting, job management) |
| `trio_adapter.py` / `trio_bridge.py` | Trio integration for P2P tools |
| `configs.py` | `Configs` dataclass — YAML + env-var configuration |
| `validators.py` | `EnhancedParameterValidator` — text, model name, IPFS hash, URL validation |
| `exceptions.py` | Typed exception hierarchy (`MCPServerError` → `ToolError`, `ValidationError`, …) |
| `monitoring.py` | `EnhancedMetricsCollector` — counters, gauges, histograms, Prometheus export |
| `client.py` | `IPFSDatasetsMCPClient` — async Python client |
| `enterprise_api.py` | `EnterpriseGraphRAGAPI` — JWT auth, rate limiting, async job processing |
| `ucan_delegation.py` | `DelegationManager`, `DelegationEvaluator` — UCAN capability chains |
| `compliance_checker.py` | Rule-based compliance engine, backup management |
| `event_dag.py` | `EventDAG` — content-addressed execution history (CID-linked event nodes) |
| `p2p_service_manager.py` | `P2PServiceManager` — P2P lifecycle, workflow scheduler, peer registry |
| `mcp_p2p_transport.py` | `LengthPrefixFramer`, `PubSubBus` — libp2p transport primitives |
| `nl_ucan_policy.py` | `NLUCANPolicyCompiler` — natural language → UCAN policy |
| `policy_audit_log.py` | `PolicyAuditLog` — immutable policy-decision audit trail |

### Design principles

**Thin wrapper pattern** — each tool file (≤ 150 lines) imports from a canonical engine module and delegates all business logic there:

```python
# tools/dataset_tools/load_dataset.py  (thin MCP wrapper)
# Core implementation: ipfs_datasets_py.core_operations.dataset_loader.DatasetLoader
@tool_metadata(runtime="fastapi")
async def load_dataset(source: str, split: str = "train") -> dict:
    """Load a dataset from a local path or HuggingFace hub."""
    loader = DatasetLoader()
    return await loader.load(source, split=split)
```

**Hierarchical discovery** — 4 meta-tools expose all 51 categories; tools are imported on first use via `importlib`, keeping startup fast and avoiding loading unused heavy dependencies.

**anyio compatibility** — all `async def` tool functions use `anyio` primitives so they run correctly in both asyncio (FastAPI) and Trio (P2P) runtimes.

**Graceful degradation** — optional heavy dependencies (Trio, libp2p, torch, GPU libraries) are imported lazily with clean fallbacks so the server starts in minimal environments.

---

## Dispatch Pipeline

Every call to `tools_dispatch` passes through a configurable staged pipeline before the tool function executes. Each stage can allow or deny the invocation:

```
PipelineIntent (tool_name, actor, params)
        │
        ▼
┌── COMPLIANCE stage ──────────────────────────────┐
│   compliance_checker.py  · rule-based enforcement │
│   fail_open=True (deny only if explicitly blocked)│
└──────────────────────────────────────────────────┘
        │
        ▼
┌── RISK stage ─────────────────────────────────────┐
│   risk_scorer.py  · numeric risk score per intent  │
│   high-risk intents can be blocked or logged       │
└───────────────────────────────────────────────────┘
        │
        ▼
┌── DELEGATION stage ───────────────────────────────┐
│   ucan_delegation.py  · UCAN chain evaluation      │
│   checks capability, expiry, revocation            │
└───────────────────────────────────────────────────┘
        │
        ▼
┌── POLICY stage ────────────────────────────────────┐
│   temporal_policy.py  · time-bounded deontic rules │
│   obligation / permission / prohibition evaluation │
└────────────────────────────────────────────────────┘
        │
        ▼
┌── NL_UCAN_GATE stage ─────────────────────────────┐
│   nl_ucan_policy.py  · natural-language policies   │
│   CIDv1-addressed compiled policy objects          │
└───────────────────────────────────────────────────┘
        │
        ▼
  Tool function executes
        │
        ▼
  EventDAG.append(EventNode(…))   ← provenance record emitted
```

`PipelineResult.allowed` summarises the overall verdict. `PipelineResult.denied_by` names the blocking stage when a call is rejected. Each stage emits a `StageMetric` with timing and reason, which is available for observability.

Construct pipelines with the factory helpers:

```python
from ipfs_datasets_py.mcp_server.dispatch_pipeline import make_default_pipeline, make_full_pipeline

pipeline = make_full_pipeline()          # all stages enabled
pipeline = make_default_pipeline()       # minimal (compliance + delegation)
result   = pipeline.run(intent)
```

---

## Authorization & Compliance (MCP++)

### UCAN Delegation

`ucan_delegation.py` implements capability-based authorization using UCAN tokens:

```python
from ipfs_datasets_py.mcp_server.ucan_delegation import DelegationManager
from ipfs_datasets_py.mcp_server.ucan_delegation import DelegationToken, Capability

# Mint a delegation token
token = DelegationToken(
    issuer="did:key:alice",
    audience="did:key:bob",
    capabilities=[Capability(ability="read", resource="dataset/squad")],
    expiry=time.time() + 3600,
)

mgr = DelegationManager()
cid = mgr.add(token)                                   # → CIDv1 string

# Check if an actor can invoke a tool
evaluator = mgr.get_evaluator()
allowed = evaluator.can_invoke("did:key:bob", "load_dataset", leaf_cid=cid)

# Query active delegations
for cid, tok in mgr.active_tokens_by_actor("did:key:bob"):
    print(cid, tok.capabilities)
```

Wildcard resource matching: `Capability(ability="read", resource="*")` matches any resource.

### Natural-Language Policy Compiler

`nl_ucan_policy.py` compiles human-readable policy strings into executable UCAN `PolicyObject` values, with CIDv1 addressing for storage and retrieval:

```python
from ipfs_datasets_py.mcp_server.nl_ucan_policy import NLUCANPolicyCompiler

compiler = NLUCANPolicyCompiler()
results = compiler.compile_batch(["Only Alice may read dataset X"])
results_with_explain = compiler.compile_batch_with_explain(
    ["Only Alice may read dataset X"],
    fail_fast=False,
)
```

### Event-DAG Provenance

`event_dag.py` maintains an append-only, content-addressed execution history. Every tool invocation emits an `EventNode` that links to its causal parents:

```python
from ipfs_datasets_py.mcp_server.event_dag import EventDAG, EventNode

dag = EventDAG()
cid_a = dag.append(EventNode(parents=[], intent_cid="bafy…", tool_name="load_dataset"))
cid_b = dag.append(EventNode(parents=[cid_a], intent_cid="bafy…", tool_name="process_dataset"))

# Trace provenance of cid_b back to its roots
history = dag.walk(cid_b)

# Find concurrent events (those with disjoint parent sets)
frontier = dag.frontier()
```

### Policy Audit Log

`policy_audit_log.py` records every policy gate decision with zero overhead when disabled:

```python
from ipfs_datasets_py.mcp_server.policy_audit_log import get_audit_log

log = get_audit_log()    # process-global singleton
log.record(policy_cid="bafy…", actor="alice", tool="load_dataset", outcome="allow")
recent = log.recent(n=50)
log.export_jsonl("/var/log/mcp_policy.jsonl")
```

---

## Configuration

Configuration is loaded in priority order: programmatic overrides → YAML file → defaults.

### YAML configuration file

```yaml
# Server transport
host: 127.0.0.1
port: 5000
transport: stdio        # "stdio" for AI clients, "http" for REST API

# IPFS Kit integration
ipfs_kit:
  integration: direct   # "direct" (import) or "mcp" (proxy to another MCP server)
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

`client.py` provides `IPFSDatasetsMCPClient`, a convenience async wrapper around the REST API:

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

For low-level parallel dispatch, use `HierarchicalToolManager` directly:

```python
import anyio
from ipfs_datasets_py.mcp_server.hierarchical_tool_manager import HierarchicalToolManager

async def main():
    manager = HierarchicalToolManager()

    results = await manager.dispatch_parallel([
        {"category": "dataset_tools",  "tool": "load_dataset",      "params": {"source": "squad"}},
        {"category": "graph_tools",    "tool": "query_knowledge_graph"},
        {"category": "vector_tools",   "tool": "search_vector_index", "params": {"query": "AI"}},
    ], max_concurrent=4)

anyio.run(main)
```

---

## P2P Capabilities

The server supports optional peer-to-peer features via the MCP++ layer (`p2p_service_manager.py`). P2P tools run in the Trio runtime for structured concurrency:

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

print(manager.get_capabilities())      # inspect available features

scheduler = manager.get_workflow_scheduler()   # None if unavailable
registry  = manager.get_peer_registry()        # None if unavailable
```

The PubSub bus (`mcp_p2p_transport.py`) handles peer communication:

```python
from ipfs_datasets_py.mcp_server.mcp_p2p_transport import PubSubBus

bus = PubSubBus()
sid = bus.subscribe("mcp/receipts/1.0", handler)
bus.publish("mcp/receipts/1.0", message)
count = bus.subscription_count("mcp/receipts/1.0")
bus.unsubscribe(sid)
```

P2P features degrade gracefully: if `ipfs_accelerate_py` or Trio are not installed, the server still starts and all non-P2P tools work normally.

---

## Error Handling

All server errors descend from `MCPServerError` in `exceptions.py`:

```
MCPServerError
├── ToolError
│   ├── ToolNotFoundError      — category or function name not found
│   ├── ToolExecutionError     — tool raised an exception at runtime
│   └── ToolRegistrationError  — duplicate or invalid tool registration
├── ValidationError            — invalid input parameter (text, hash, model name, …)
├── RuntimeRoutingError
│   ├── RuntimeNotFoundError   — requested runtime (trio/fastapi) unavailable
│   └── RuntimeExecutionError  — runtime-level dispatch failure
├── P2PServiceError
│   ├── P2PConnectionError     — libp2p connection failure
│   └── P2PAuthenticationError — UCAN/auth failure for P2P call
├── ConfigurationError         — invalid or missing config key
├── ServerStartupError         — server could not initialise
├── ServerShutdownError        — error during cleanup
├── HealthCheckError           — health-check reported unhealthy
└── MonitoringError
    └── MetricsCollectionError — metrics backend failure
```

Input validation is handled by `EnhancedParameterValidator` (`validators.py`), which validates:

- **Text** — length bounds (default 1–10,000 chars), sanitisation against dangerous patterns
- **Model names** — must match known provider prefixes (`sentence-transformers/`, `openai/`, `cohere/`, `huggingface/`, `local/`, etc.)
- **IPFS hashes** — CIDv0 (`Qm…` 46 chars) and CIDv1 (`baf…` 58+ chars)
- **Collection names** — alphanumeric, hyphens, underscores only
- **URLs** — scheme + netloc validation, optional allow-list enforcement
- **Numeric ranges** — min/max bounds with type coercion

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

Tests follow the **GIVEN-WHEN-THEN** pattern. Runtime-specific tests use `anyio.pytest_plugin` to parameterise over both `asyncio` and `trio` backends.

---

## Contributing

1. Read [QUICKSTART.md](QUICKSTART.md) — setup and running tests.
2. Read [THIN_TOOL_ARCHITECTURE.md](THIN_TOOL_ARCHITECTURE.md) — the thin-wrapper pattern.
3. Read [docs/development/tool-patterns.md](docs/development/tool-patterns.md) — how to add a new tool.
4. Add tests following the GIVEN-WHEN-THEN pattern used throughout `tests/mcp/`.
5. Keep tool files under 150 lines; business logic goes in `ipfs_datasets_py.<domain>.<name>_engine.py`.
6. Add type hints and docstrings; avoid bare `except` clauses.
7. Run the checks below before opening a PR.

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
| [THIN_TOOL_ARCHITECTURE.md](THIN_TOOL_ARCHITECTURE.md) | Thin-wrapper design and ADR rationale |
| [SECURITY.md](SECURITY.md) | Security posture and hardening notes |
| [CHANGELOG.md](CHANGELOG.md) | Version history |
| [docs/api/tool-reference.md](docs/api/tool-reference.md) | Full API reference — all 51 categories |
| [docs/architecture/dual-runtime.md](docs/architecture/dual-runtime.md) | FastAPI + Trio dual-runtime design |
| [docs/architecture/mcp-plus-plus-alignment.md](docs/architecture/mcp-plus-plus-alignment.md) | UCAN, event-DAG, P2P transport, compliance |
| [docs/architecture/adr/](docs/architecture/adr/) | Architecture Decision Records (ADR-001 – ADR-006) |
| [docs/guides/cookbook.md](docs/guides/cookbook.md) | Usage recipes: parallel dispatch, streaming, batching |
| [docs/guides/p2p-migration.md](docs/guides/p2p-migration.md) | Migrating to P2P-backed tools |
| [docs/guides/performance-tuning.md](docs/guides/performance-tuning.md) | Connection pools, concurrency limits, caches |
| [docs/development/tool-patterns.md](docs/development/tool-patterns.md) | How to write a new tool |
| [docs/testing/DUAL_RUNTIME_TESTING_STRATEGY.md](docs/testing/DUAL_RUNTIME_TESTING_STRATEGY.md) | Testing dual-runtime code with anyio |
