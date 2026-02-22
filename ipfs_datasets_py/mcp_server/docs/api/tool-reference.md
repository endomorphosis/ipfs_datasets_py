# IPFS Datasets MCP Server API Reference

This document provides a reference for the MCP server API tools available in the IPFS Datasets Python package. These tools can be accessed through the Model Context Protocol by AI assistants like Claude.

## Server Configuration

The IPFS Datasets MCP server can be configured using:

1. **Command line arguments**:
   - `--host`: Host to bind the server to (default: 0.0.0.0)
   - `--port`: Port to bind the server to (default: 8000)
   - `--config`: Path to a configuration YAML file
   - `--ipfs-kit-mcp-url`: URL of an ipfs_kit_py MCP server

2. **Configuration file** (YAML format):
   ```yaml
   server:
     host: "127.0.0.1"
     port: 8000
     log_level: "INFO"
     verbose: true
     tool_timeout: 60
     transport: "stdio"
   
   tools:
     enabled_categories:
       - dataset
       - ipfs
       - vector
       - graph
       - audit
       - security
       - provenance
   
   ipfs_kit:
     integration: "mcp"  # or "direct"
     mcp_url: "http://localhost:8001"
   ```

## Dataset Tools

### load_dataset

Load a dataset from a file or IPFS source.

**Parameters:**
- `source` (str): Source path or identifier of the dataset (local file path or IPFS CID)
- `format` (str, optional): Format of the dataset (json, csv, parquet, etc.; auto-detected if not provided)
- `options` (dict, optional): Additional options for loading the dataset

**Returns:**
```json
{
  "status": "success",
  "dataset_id": "d12345",
  "metadata": {
    "name": "Example Dataset",
    "format": "json",
    "record_count": 100,
    "columns": ["id", "name", "value"]
  }
}
```

### save_dataset

Save a dataset to a destination.

**Parameters:**
- `dataset_id` (str): The ID of the dataset to save
- `destination` (str): Destination path or location to save the dataset
- `format` (str, optional): Format to save the dataset in
- `options` (dict, optional): Additional options for saving the dataset

**Returns:**
- Dictionary containing information about the saved dataset

### process_dataset

Process a dataset with a series of operations.

**Parameters:**
- `dataset_id` (str): The ID of the dataset to process
- `operations` (list): List of operations to apply to the dataset
- `output_id` (str, optional): Optional ID for the resulting dataset

**Returns:**
- Dictionary containing information about the processed dataset

### convert_dataset_format

Convert a dataset to a different format.

**Parameters:**
- `dataset_id` (str): The ID of the dataset to convert
- `target_format` (str): The format to convert the dataset to
- `output_path` (str, optional): Optional path to save the converted dataset
- `options` (dict, optional): Additional options for the conversion

**Returns:**
- Dictionary containing information about the converted dataset

## IPFS Tools

### pin_to_ipfs

Pin a file or directory to IPFS.

**Parameters:**
- `content_path` (str): Path to the file or directory to pin
- `recursive` (bool, optional): Whether to add the directory recursively
- `wrap_with_directory` (bool, optional): Whether to wrap the file(s) in a directory
- `hash_algo` (str, optional): The hash algorithm to use

**Returns:**
- Dictionary containing information about the pinned content

### get_from_ipfs

Get content from IPFS by its CID.

**Parameters:**
- `cid` (str): The Content Identifier (CID) to retrieve
- `output_path` (str, optional): Path where to save the retrieved content
- `timeout_seconds` (int, optional): Timeout for the retrieval operation in seconds

**Returns:**
- Dictionary containing information about the retrieved content

## Vector Tools

### create_vector_index

Create a vector index for similarity search.

**Parameters:**
- `vectors` (list): List of vectors to index
- `dimension` (int, optional): Dimension of the vectors
- `metric` (str, optional): Distance metric to use
- `metadata` (list, optional): Optional metadata for each vector
- `index_id` (str, optional): Optional ID for the index
- `index_name` (str, optional): Optional name for the index

**Returns:**
- Dictionary containing information about the created index

### search_vector_index

Search a vector index for similar vectors.

**Parameters:**
- `index_id` (str): ID of the vector index to search
- `query_vector` (list): The query vector to search for
- `top_k` (int, optional): Number of results to return
- `include_metadata` (bool, optional): Whether to include metadata in the results
- `include_distances` (bool, optional): Whether to include distance values in the results
- `filter_metadata` (dict, optional): Optional filter to apply to metadata

**Returns:**
- Dictionary containing search results

## Graph Tools

### query_knowledge_graph

Query a knowledge graph for information.

**Parameters:**
- `graph_id` (str): ID of the knowledge graph to query
- `query` (str): The query string (SPARQL, Cypher, etc.)
- `query_type` (str, optional): The type of query ('sparql', 'cypher', 'gremlin', etc.)
- `max_results` (int, optional): Maximum number of results to return
- `include_metadata` (bool, optional): Whether to include metadata in the results

**Returns:**
- Dictionary containing query results

## Audit Tools

### record_audit_event

Record an audit event for security, compliance, and operations tracking.

**Parameters:**
- `action` (str): The action being audited
- `resource_id` (str, optional): Optional ID of the resource being acted upon
- `resource_type` (str, optional): Optional type of the resource being acted upon
- `user_id` (str, optional): Optional ID of the user performing the action
- `details` (dict, optional): Optional additional details about the event
- `source_ip` (str, optional): Optional source IP address
- `severity` (str, optional): Severity level ('info', 'warning', 'error', 'critical')
- `tags` (list, optional): Optional tags for categorizing the event

**Returns:**
- Dictionary containing information about the recorded audit event

### generate_audit_report

Generate an audit report based on audit logs.

**Parameters:**
- `report_type` (str, optional): Type of report ('summary', 'detailed', 'security', 'compliance')
- `start_time` (str, optional): Optional start time for the report period (ISO format)
- `end_time` (str, optional): Optional end time for the report period (ISO format)
- `filters` (dict, optional): Optional filters to apply to the audit logs
- `output_format` (str, optional): Format of the report ('json', 'csv', 'html', 'pdf')
- `output_path` (str, optional): Optional path to save the report
- `include_details` (bool, optional): Whether to include detailed information in the report

**Returns:**
- Dictionary containing information about the generated report

## Security Tools

### check_access_permission

Check if a user has permission to access a resource.

**Parameters:**
- `resource_id` (str): ID of the resource to check
- `user_id` (str): ID of the user to check permissions for
- `permission_type` (str, optional): Type of permission to check ('read', 'write', 'delete', 'share', etc.)
- `resource_type` (str, optional): Optional type of the resource

**Returns:**
- Dictionary containing permission information

## Provenance Tools

### record_provenance

Record provenance information for a dataset operation.

**Parameters:**
- `dataset_id` (str): ID of the dataset
- `operation` (str): The operation performed on the dataset
- `inputs` (list, optional): Optional list of input dataset IDs or sources
- `parameters` (dict, optional): Optional parameters used in the operation
- `description` (str, optional): Optional description of the operation
- `agent_id` (str, optional): Optional ID of the agent performing the operation
- `timestamp` (str, optional): Optional timestamp for the operation (ISO format)
- `tags` (list, optional): Optional tags for categorizing the provenance record

**Returns:**
- Dictionary containing information about the recorded provenance

---

## Complete Tool Category Reference

The following table lists all 49 tool categories.  Each category corresponds to a
directory under `ipfs_datasets_py/mcp_server/tools/`.

| Category | Directory | Purpose |
|---|---|---|
| Admin | `admin_tools/` | User & role management, server configuration |
| Alert | `alert_tools/` | Discord notifications, alert rule engine |
| Analysis | `analysis_tools/` | Data analysis, statistical summaries |
| Audit | `audit_tools/` | Immutable audit log, compliance reporting |
| Auth | `auth_tools/` | Token generation, ACL enforcement |
| Background Tasks | `background_task_tools/` | Async task submission & status |
| Bespoke | `bespoke_tools/` | Custom one-off tools & extensions |
| Cache | `cache_tools/` | TTL cache inspection, invalidation |
| Dashboard | `dashboard_tools/` | JS error reporter, TDFOL performance charts |
| Data Processing | `data_processing_tools/` | ETL pipelines, data normalisation |
| Dataset | `dataset_tools/` | Load / save / convert / process datasets |
| Development | `development_tools/` | Linting, test running, code review |
| Discord | `discord_tools/` | Discord channel listing, message export |
| Email | `email_tools/` | IMAP/SMTP connect, export, analyse |
| Embedding | `embedding_tools/` | Generate, index, and search embeddings |
| File Converter | `file_converter_tools/` | Convert between file formats |
| File Detection | `file_detection_tools/` | MIME type detection, file info |
| Finance Data | `finance_data_tools/` | Market data, stock screening |
| Geospatial | `geospatial_tools/` | Coordinate lookup, spatial queries |
| Graph | `graph_tools/` | Knowledge graph CRUD & Cypher queries |
| Index Management | `index_management_tools/` | Vector index build, reindex, delete |
| Investigation | `investigation_tools/` | Entity analysis, relationship timelines |
| IPFS Cluster | `ipfs_cluster_tools/` | Cluster peer management, pin status |
| IPFS | `ipfs_tools/` | Pin, get, add, CAR conversion |
| Legal Dataset | `legal_dataset_tools/` | Scrape & query legal corpus |
| Logic | `logic_tools/` | CEC/TDFOL theorem proving tools |
| Media | `media_tools/` | FFmpeg convert/edit/analyse, yt-dlp |
| Medical Research | `medical_research_scrapers/` | PubMed scraping, medical theorms |
| Monitoring | `monitoring_tools/` | Metrics collection, health checks |
| P2P | `p2p_tools/` | Peer status, distributed cache & task queue |
| P2P Workflow | `p2p_workflow_tools/` | Distributed workflow scheduling |
| PDF | `pdf_tools/` | Extract text, entities, cross-doc analysis |
| Provenance | `provenance_tools/` | Record & query data lineage |
| Rate Limiting | `rate_limiting_tools/` | Rate-limit configuration & status |
| Search | `search_tools/` | Semantic search, BM25, hybrid |
| Security | `security_tools/` | Access control, vulnerability scanning |
| Session | `session_tools/` | Session create/resume/close |
| Software Engineering | `software_engineering_tools/` | Repo analysis, dependency graphs |
| Sparse Embedding | `sparse_embedding_tools/` | SPLADE/BM25 sparse vectors |
| Storage | `storage_tools/` | Multi-backend storage (memory, IPFS, S3) |
| Vector Store | `vector_store_tools/` | FAISS / Qdrant / Elasticsearch CRUD |
| Vector | `vector_tools/` | ANN search, distance computation |
| Web Archive | `web_archive_tools/` | Common Crawl, Wayback Machine, WARC |
| Web Scraping | `web_scraping_tools/` | Autoscraper, structured-data extraction |
| Workflow | `workflow_tools/` | DAG workflows, parallel execution |

---

## Admin Tools

### manage_users
Manage server users and roles.

**Parameters:**
- `action` (str): `create` | `delete` | `list` | `update`
- `username` (str, optional): Username to operate on
- `role` (str, optional): Role name (`admin`, `user`, `readonly`)

**Returns:** `{"status": "success", "users": [...]}` or error dict.

### manage_server_config
Read or update server configuration at runtime.

**Parameters:**
- `action` (str): `get` | `set` | `reset`
- `key` (str, optional): Config key path (dot-notation)
- `value` (Any, optional): New value for `set` action

---

## Alert Tools

### send_discord_message
Send a plain-text message to a Discord channel.

**Parameters:**
- `text` (str): Message body
- `role_names` (list[str], optional): Roles to mention
- `channel_id` (str, optional): Target channel (uses default if omitted)

**Returns:** `{"status": "sent", "message_id": "..."}` or error dict.

### evaluate_alert_rules
Evaluate an event against all registered alert rules.

**Parameters:**
- `event` (dict): Event data to evaluate (arbitrary key/value pairs)

**Returns:** List of triggered rule names and actions taken.

---

## Dataset Tools (extended)

### convert_dataset
Convert a dataset between supported formats.

**Parameters:**
- `dataset_id` (str): Source dataset ID
- `target_format` (str): `csv` | `parquet` | `json` | `jsonl` | `arrow`
- `destination` (str): Output path

**Returns:** `{"status": "success", "output_path": "..."}`.

---

## Graph Tools (extended)

### graph_add_entity
Add an entity node to an existing knowledge graph.

**Parameters:**
- `graph_id` (str): Target graph ID
- `entity_name` (str): Human-readable name
- `entity_type` (str, optional): Ontology type (e.g., `Person`, `Organization`)
- `properties` (dict, optional): Additional properties

**Returns:** `{"success": true, "entity_id": "..."}`.

### graph_add_relationship
Add a directed edge between two entities.

**Parameters:**
- `graph_id` (str)
- `source_entity_id` (str)
- `target_entity_id` (str)
- `relationship_type` (str): Edge label (e.g., `WORKS_FOR`)
- `properties` (dict, optional)

### graph_query_cypher
Execute a Cypher query against the graph.

**Parameters:**
- `graph_id` (str)
- `query` (str): Cypher query string

**Returns:** `{"success": true, "results": [...]}`.

---

## Embedding Tools (extended)

### generate_embedding
Generate a vector embedding for a text string.

**Parameters:**
- `text` (str): Input text
- `model` (str, optional): Model identifier (default: `sentence-transformers/all-MiniLM-L6-v2`)
- `normalize` (bool, optional): L2-normalise output (default: `true`)

**Returns:** `{"success": true, "embedding": [...], "dimensions": N}`.

### batch_generate_embeddings
Generate embeddings for a list of texts.

**Parameters:**
- `texts` (list[str]): Input texts (max 512 per call)
- `model` (str, optional)

**Returns:** `{"success": true, "embeddings": [[...], ...]}`.

---

## Monitoring Tools (extended)

### get_metrics
Retrieve a snapshot of all server metrics.

**Returns:**
```json
{
  "uptime_seconds": 3600,
  "request_metrics": {"total_requests": 1000, "error_rate": 0.01},
  "tool_metrics": {"dataset_tools/load_dataset": {"total_calls": 50, "p99_ms": 42}},
  "tool_latency_percentiles": {"dataset_tools/load_dataset": {"p50": 12, "p95": 38, "p99": 42}}
}
```

### get_tool_latency_percentiles
Retrieve p50/p95/p99 latency histogram for a specific tool.

**Parameters:**
- `tool_name` (str): Exact tool name as tracked internally

**Returns:**
```json
{"p50": 12.0, "p95": 38.0, "p99": 42.0, "min": 5.0, "max": 200.0, "count": 1000}
```

---

## P2P Tools

### p2p_service_status
Return local P2P service status and recently-seen peers.

**Parameters:**
- `include_peers` (bool, optional): Include peer list (default: `true`)
- `peers_limit` (int, optional): Max peers to return (default: 50)

**Returns:** `{"status": "running", "peer_count": 12, "peers": [...]}`.

### p2p_cache_get / p2p_cache_set / p2p_cache_has / p2p_cache_delete
Operate on the distributed P2P cache.

### p2p_task_submit
Submit a task to the local P2P task queue.

**Parameters:**
- `task_type` (str): Task type identifier
- `payload` (dict): Arbitrary task payload
- `model_name` (str, optional): Target model

**Returns:** `{"task_id": "...", "status": "queued"}`.

---

## Security Tools

### check_access_permission
Check whether a principal has a specific permission.

**Parameters:**
- `principal_id` (str): User or service identifier
- `resource` (str): Resource path or name
- `action` (str): Requested action (`read` | `write` | `delete` | `execute`)

**Returns:** `{"allowed": true/false, "reason": "..."}`.

---

## Storage Tools

### store_data
Persist arbitrary data in the configured storage backend.

**Parameters:**
- `data` (str | bytes | dict | list): Data to store
- `storage_type` (str, optional): `memory` | `ipfs` | `s3` | `disk` (default: `memory`)
- `collection` (str, optional): Logical collection name
- `compression` (str, optional): `none` | `gzip` | `zstd`

**Returns:** `{"success": true, "storage_id": "..."}`.

### retrieve_data
Retrieve previously stored data by ID.

**Parameters:**
- `storage_id` (str): ID returned by `store_data`
- `collection` (str, optional)

**Returns:** `{"success": true, "data": ...}`.

---

## Web Archive Tools

### search_common_crawl
Search the Common Crawl index for pages matching a query.

**Parameters:**
- `query` (str): Search query
- `max_results` (int, optional): Maximum results (default: 10)
- `index_name` (str, optional): Specific CC index (default: latest)

**Returns:** `{"success": true, "results": [...], "total_found": N}`.

### search_serpstack / search_openverse
Thin wrappers forwarding to the web-archiving canonical engines.

---

## Phase G/H Additions (v6.0)

> The following APIs were added in **v6.0** as part of phases G (coverage hardening)
> and H (integration / scenario tests).

### CircuitBreaker

Located in `hierarchical_tool_manager.py`.

Prevents cascading failures when a downstream tool or service becomes
unreliable.  Transitions: **CLOSED** → **OPEN** (on repeated failures) →
**HALF_OPEN** (probe after recovery window) → **CLOSED** (on probe success).

```python
from ipfs_datasets_py.mcp_server.hierarchical_tool_manager import CircuitBreaker

breaker = CircuitBreaker(
    name="my_service",
    failure_threshold=5,   # trips after 5 consecutive failures
    recovery_timeout=30.0, # seconds before probing again
)

result = await breaker.call(my_async_func, arg1, arg2)
print(breaker.state)   # "closed", "open", or "half_open"
print(breaker.info())  # {"name": ..., "state": ..., "failure_count": ..., ...}
breaker.reset()        # force back to CLOSED
```

**`CircuitBreaker.call(func, *args, **kwargs)`**
- Raises `CircuitBreakerOpenError` when the circuit is OPEN.
- Passes `KeyboardInterrupt` / `SystemExit` through unchanged.
- On failure increments the internal counter; on success resets it.

---

### dispatch_parallel (v6.0 — adaptive batching)

`HierarchicalToolManager.dispatch_parallel` now accepts a `max_concurrent`
parameter for **adaptive batch sizing**.

```python
results = await manager.dispatch_parallel(
    calls=[
        {"category": "dataset_tools", "tool": "load_dataset", "params": {"source": "squad"}},
        {"category": "graph_tools",   "tool": "query_knowledge_graph"},
        # ... many more ...
    ],
    max_concurrent=4,   # process at most 4 calls at a time
    return_exceptions=True,
)
```

**Parameters (v6.0 additions):**
- `max_concurrent` (`int | None`, default `None`): When set, calls are
  processed in windows of this size rather than all at once.  Useful when
  the call list is very large or when downstream services have rate limits.
  When `None` (default) all calls run concurrently (original behaviour).

---

### Enterprise API — JWT Authentication

`AuthenticationManager` (in `enterprise_api.py`) now supports **token
revocation** to support logout and token-rotation workflows.

```python
from ipfs_datasets_py.mcp_server.enterprise_api import AuthenticationManager

auth = AuthenticationManager(secret_key="super-secret")
token = auth.create_access_token("demo")

# Verify (returns user dict or None)
user_data = auth.verify_token(token)

# Revoke (returns True on success, False if token is unparseable)
revoked = auth.revoke_token(token)

# Subsequent verify calls return None for revoked tokens
assert auth.verify_token(token) is None
assert auth.is_token_revoked(token) is True
```

**New methods:**

| Method | Returns | Description |
|---|---|---|
| `revoke_token(token)` | `bool` | Add token to the revocation list |
| `is_token_revoked(token)` | `bool` | Check if token has been revoked |

> **Production note:** The in-memory revocation store (`_revoked_tokens` set)
> is lost on process restart.  In production replace it with a Redis or
> database-backed store.

---

### Monitoring — Enhanced Metrics (v6.0)

`EnhancedMetricsCollector` coverage was extended to 80%+ in v6.0.

Key paths now covered include:
- `_start_monitoring` / `start_monitoring` async startup
- `track_request` context manager with exception propagation
- `_check_health` with `HealthCheckError` and `ImportError` handling
- `_check_alerts` (response-time threshold alert)
- `get_tool_latency_percentiles` (P50/P90/P99)
- `get_performance_trends` (time-windowed statistics)
- `shutdown` method (graceful teardown)
- `P2PMetricsCollector.get_dashboard_data` cache hit path

---

## Ecosystem Integrations (v6.0)

### gRPC Transport Adapter

`grpc_transport.py` — wraps `HierarchicalToolManager` behind a gRPC service.

```python
from ipfs_datasets_py.mcp_server.grpc_transport import GRPCTransportAdapter

adapter = GRPCTransportAdapter(manager, port=50051)
await adapter.start()   # requires grpcio
info = adapter.get_info()
# {"transport": "grpc", "host": "[::]", "port": 50051, ...}
await adapter.stop()
```

### Prometheus Exporter

`prometheus_exporter.py` — bridges the metrics collector to Prometheus.

```python
from ipfs_datasets_py.mcp_server.prometheus_exporter import PrometheusExporter

exporter = PrometheusExporter(collector=get_metrics_collector(), port=9090)
exporter.start_http_server()   # requires prometheus-client
exporter.record_tool_call("dataset_tools", "load_dataset", "success", 0.042)
exporter.update()              # sync latest metrics
info = exporter.get_info()
```

Metrics exposed: `mcp_tool_calls_total`, `mcp_tool_latency_seconds`,
`mcp_active_connections`, `mcp_error_rate`, `mcp_cache_hits_total`,
`mcp_cache_misses_total`, `mcp_system_cpu_usage_percent`,
`mcp_system_memory_usage_percent`, `mcp_uptime_seconds`.

### OpenTelemetry Tracing

`otel_tracing.py` — distributed tracing for tool dispatches.

```python
from ipfs_datasets_py.mcp_server.otel_tracing import configure_tracing, MCPTracer

configure_tracing(service_name="my-mcp-server", otlp_endpoint="http://localhost:4317")

tracer = MCPTracer()
with tracer.start_dispatch_span("dataset_tools", "load_dataset", {"source": "squad"}) as span:
    result = await manager.dispatch("dataset_tools", "load_dataset", {"source": "squad"})
    tracer.set_span_ok(span, result)
```

---

*This reference is auto-generated from tool docstrings and the
`THIN_TOOL_ARCHITECTURE.md` design document.  See individual source files
under `ipfs_datasets_py/mcp_server/tools/` for full parameter details.*
