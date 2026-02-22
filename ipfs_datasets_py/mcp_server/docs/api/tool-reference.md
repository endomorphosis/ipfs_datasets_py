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

## Analysis Tools

Statistical analysis and pattern detection over datasets.

### analyze_data
**Parameters:**
- `data_source` (str, required) — Dataset id or path.
- `analysis_type` (str, optional) — `"statistics"` | `"patterns"` | `"comparison"` (default: `"statistics"`).
- `columns` (list[str], optional) — Subset of columns to analyse.
- `output_format` (str, optional) — `"json"` | `"html"` (default: `"json"`).

**Returns:** `{"status": "success", "result": {"mean": {...}, "std": {...}, ...}}`.

### generate_statistics
Compute descriptive statistics (mean, median, stddev, quartiles).

**Parameters:** `data_source` (str), `columns` (list[str], optional).

**Returns:** `{"status": "success", "statistics": {...}}`.

### detect_patterns
Identify repeating patterns, seasonality, or anomalies in a dataset.

**Parameters:** `data_source` (str), `pattern_type` (str, optional).

**Returns:** `{"status": "success", "patterns": [...]}`.

---

## Auth Tools

Authentication, token management, and user administration.

### create_api_key
Create a new API key for a user or service.

**Parameters:** `user_id` (str), `description` (str, optional), `expires_in_days` (int, optional).

**Returns:** `{"api_key": "ak_...", "expires_at": "..."}`.

### validate_token
Validate a JWT or API key and return the associated principal.

**Parameters:** `token` (str), `token_type` (str, optional — `"jwt"` | `"api_key"`).

**Returns:** `{"valid": true, "user_id": "...", "roles": [...]}`.

### revoke_token
Revoke an active token.

**Parameters:** `token` (str).

**Returns:** `{"status": "success"}`.

---

## Background Task Tools

Submit and monitor long-running asynchronous jobs.

### submit_background_task
**Parameters:**
- `task_type` (str, required) — Type identifier.
- `payload` (dict, required) — Task-specific parameters.
- `priority` (int, optional, default 5) — 1=highest, 10=lowest.

**Returns:** `{"task_id": "uuid", "status": "queued"}`.

### get_task_status
**Parameters:** `task_id` (str, required).

**Returns:** `{"task_id": "...", "status": "running|completed|failed", "progress": 0.0–1.0}`.

### cancel_task
**Parameters:** `task_id` (str, required).

**Returns:** `{"status": "cancelled"}`.

---

## Cache Tools

In-memory and distributed caching operations.

### cache_get
**Parameters:** `key` (str), `namespace` (str, optional).

**Returns:** `{"hit": true, "value": ...}` or `{"hit": false}`.

### cache_set
**Parameters:** `key` (str), `value` (any), `ttl_seconds` (int, optional), `namespace` (str, optional).

**Returns:** `{"status": "success"}`.

### cache_delete
**Parameters:** `key` (str), `namespace` (str, optional).

**Returns:** `{"deleted": true}`.

### cache_stats
Returns hit/miss statistics for the named namespace.

**Parameters:** `namespace` (str, optional).

**Returns:** `{"hits": int, "misses": int, "hit_rate": float, "size_bytes": int}`.

---

## CLI Tools

Execute shell commands and invoke CLI-based utilities from within the MCP server.

### execute_command
Execute a shell command in a sandboxed, controlled environment.

**Parameters:**
- `command` (list[str], required) — Command and arguments (no shell injection).
- `timeout` (int, optional, default 30) — Seconds before timeout.
- `capture_stderr` (bool, optional, default false).

**Returns:** `{"status": "success", "exit_code": 0, "stdout": "...", "stderr": "..."}`.

> ⚠️ For security, `execute_command` is a sandboxed stub in the current implementation. Sensitive operations are logged and rejected.

---

## Dashboard Tools

Aggregated system and performance dashboards.

### get_system_dashboard
Returns a consolidated system dashboard snapshot (CPU, memory, request rate, error rate).

**Returns:** `{"cpu_percent": float, "memory_percent": float, "request_rate": float, ...}`.

### get_tool_performance_dashboard
Returns per-tool performance statistics.

**Returns:** `{"tools": {"tool_name": {"calls": int, "avg_ms": float, "error_rate": float}}}`.

---

## Data Processing Tools

Text chunking, schema validation, format conversion, and data normalisation.

### chunk_text
Split text into fixed-size or sentence-aligned chunks for LLM ingestion.

**Parameters:**
- `text` (str, required).
- `chunk_size` (int, optional, default 512) — Tokens per chunk.
- `overlap` (int, optional, default 50).
- `strategy` (str, optional) — `"sentence"` | `"paragraph"` | `"fixed"`.

**Returns:** `{"chunks": ["...", "..."], "count": int}`.

### transform_data
Apply a named transformation pipeline to a dataset.

**Parameters:** `dataset_id` (str), `pipeline` (list[str]).

**Returns:** `{"status": "success", "dataset_id": "..."}`.

### convert_format
Convert a file between formats.

**Parameters:** `input_path` (str), `output_format` (str), `output_path` (str, optional).

**Returns:** `{"status": "success", "output_path": "..."}`.

### validate_schema
Validate a dataset against a JSON/Pydantic schema.

**Parameters:** `data` (dict | list), `schema` (dict).

**Returns:** `{"valid": true}` or `{"valid": false, "errors": [...]}`.

---

## Development Tools

Code quality, linting, testing, and CI/CD integration tools.

### lint_code
Run flake8/ruff linting on a Python source file or directory.

**Parameters:** `path` (str), `rules` (list[str], optional), `max_line_length` (int, optional, default 120).

**Returns:** `{"issues": [...], "issue_count": int}`.

### run_tests
Execute pytest on a given path and return a pass/fail summary.

**Parameters:** `test_path` (str), `markers` (str, optional), `verbose` (bool, optional).

**Returns:** `{"passed": int, "failed": int, "errors": int, "output": "..."}`.

### create_github_pr
Create a GitHub pull request (requires `GITHUB_TOKEN` env var).

**Parameters:** `title` (str), `body` (str), `head_branch` (str), `base_branch` (str, default `"main"`).

**Returns:** `{"pr_url": "...", "pr_number": int}`.

---

## Embedding Tools

Vector embedding generation for semantic search and similarity computation.

### create_embeddings
Generate a vector embedding for a text string.

**Parameters:**
- `text` (str | list[str], required) — Input text or batch.
- `model` (str, optional, default `"all-MiniLM-L6-v2"`) — Hugging Face model id.
- `normalize` (bool, optional, default true).

**Returns:** `{"embeddings": [[float, ...]], "dimensions": int, "model": "..."}`.

### batch_embeddings
Generate embeddings for a large collection with automatic batching.

**Parameters:** `texts` (list[str]), `batch_size` (int, optional, default 32), `model` (str, optional).

**Returns:** `{"embeddings": [[...]], "count": int, "dimensions": int}`.

### compute_similarity
Compute cosine similarity between two embedding vectors.

**Parameters:** `vec_a` (list[float]), `vec_b` (list[float]).

**Returns:** `{"similarity": float}`.

---

## File Converter Tools

Convert between common file formats (PDF, DOCX, HTML, Markdown, plain text).

### convert_file
**Parameters:** `input_path` (str), `output_format` (str), `output_path` (str, optional).

**Returns:** `{"status": "success", "output_path": "..."}`.

### extract_text
Extract raw text from a binary document.

**Parameters:** `file_path` (str).

**Returns:** `{"text": "...", "page_count": int}`.

---

## File Detection Tools

Detect file types, MIME types, and encoding information.

### detect_file_type
**Parameters:** `file_path` (str).

**Returns:** `{"mime_type": "application/pdf", "extension": ".pdf", "encoding": "binary"}`.

### analyze_detection_accuracy
Validate detection accuracy across a test directory.

**Parameters:** `directory` (str), `expected_types` (dict, optional).

**Returns:** `{"total_files": int, "correct": int, "accuracy": float}`.

---

## Finance Data Tools

Retrieve financial market data and apply quantitative finance theorems.

### get_market_data
**Parameters:** `symbol` (str), `period` (str, optional — `"1d"` | `"1mo"` | `"1y"`).

**Returns:** `{"open": float, "close": float, "volume": int, ...}`.

### apply_financial_theorem
Apply a named quantitative theorem (e.g. Black-Scholes, CAPM) to market data.

**Parameters:** `theorem_id` (str), `symbol` (str), `event_date` (str), `event_data` (dict).

**Returns:** `{"result": float, "theorem": "...", "confidence": float}`.

---

## Functions

Execute Python code snippets in a sandboxed environment.

### execute_python_snippet
**Parameters:**
- `code` (str, required) — Python code to execute.
- `timeout` (int, optional, default 10).
- `allowed_imports` (list[str], optional).

**Returns:** `{"status": "success", "stdout": "...", "stderr": "..."}`.

> ⚠️ Execution is sandboxed. Dangerous operations are blocked.

---

## Geospatial Tools

Geographic data processing: geocoding, distance, spatial queries.

### geocode_address
**Parameters:** `address` (str, required).

**Returns:** `{"lat": float, "lon": float, "confidence": float, "formatted": "..."}`.

### reverse_geocode
**Parameters:** `lat` (float), `lon` (float).

**Returns:** `{"address": "...", "city": "...", "country": "..."}`.

### calculate_distance
**Parameters:** `from_coords` (dict — `{lat, lon}`), `to_coords` (dict), `unit` (str — `"km"` | `"mi"`).

**Returns:** `{"distance": float, "unit": "km"}`.

---

## Graph Tools

Knowledge graph creation and querying.

### graph_create
Create a new named knowledge graph.

**Parameters:** `name` (str), `backend` (str, optional — `"networkx"` | `"neo4j"`).

**Returns:** `{"graph_id": "...", "status": "created"}`.

### graph_add_entity
**Parameters:** `graph_id` (str), `entity_id` (str), `entity_type` (str), `properties` (dict, optional).

**Returns:** `{"status": "success"}`.

### graph_add_relationship
**Parameters:** `graph_id` (str), `source_id` (str), `target_id` (str), `relation_type` (str), `properties` (dict, optional).

**Returns:** `{"status": "success"}`.

### graph_query_cypher
Run a Cypher-style query against the graph.

**Parameters:** `graph_id` (str), `query` (str).

**Returns:** `{"results": [{"nodes": [...], "edges": [...]}]}`.

### graph_search_hybrid
Hybrid keyword + vector search over graph entities.

**Parameters:** `graph_id` (str), `query` (str), `top_k` (int, optional, default 10).

**Returns:** `{"results": [{"entity": "...", "score": float}]}`.

---

## Index Management Tools

Vector and search index lifecycle management.

### create_index
**Parameters:** `name` (str), `index_type` (str — `"hnsw"` | `"flat"` | `"ivf"`), `dimensions` (int), `metric` (str, optional — `"cosine"` | `"l2"`), `backend` (str, optional).

**Returns:** `{"index_id": "...", "status": "created"}`.

### delete_index
**Parameters:** `name` (str), `backend` (str, optional).

**Returns:** `{"deleted": true}`.

### rebuild_index
**Parameters:** `name` (str), `full_rebuild` (bool, optional, default false).

**Returns:** `{"status": "success", "vectors": int}`.

### get_index_stats
**Parameters:** `name` (str).

**Returns:** `{"vectors": int, "dimensions": int, "size_mb": float, "last_updated": "..."}`.

---

## IPFS Cluster Tools

Multi-node IPFS cluster coordination.

### cluster_pin
Pin content across multiple cluster nodes.

**Parameters:** `cid` (str), `replication_factor` (int, optional, default 2), `name` (str, optional).

**Returns:** `{"cid": "...", "status": "pinned", "replicas": int}`.

### cluster_status
**Parameters:** `cid` (str).

**Returns:** `{"cid": "...", "status": "pinned", "peers": [...]}`.

### list_cluster_peers
**Returns:** `{"peers": [{"id": "...", "name": "...", "status": "connected"}]}`.

---

## Investigation Tools

Entity analysis, entity relationship investigation, and provenance tracking.

### analyze_entities
**Parameters:** `corpus_data` (list[dict]).

**Returns:** `{"entities": [...], "relationships": [...]}`.

### track_provenance
**Parameters:** `corpus_data` (list[dict]), `entity_id` (str), `include_citations` (bool, optional).

**Returns:** `{"provenance": [...]}`.

---

## Legal Dataset Tools

Legal document scraping, processing, and citation.

### scrape_recap_archive
Scrape legal filings from CourtListener/RECAP.

**Parameters:** `query` (dict — court, case_name, etc.).

**Returns:** `{"results": [...], "count": int}`.

### brave_legal_search
Full-text legal search using Brave Search API.

**Parameters:** `query` (str), `jurisdiction` (str, optional), `max_results` (int, optional).

**Returns:** `{"results": [...]}`.

### validate_bluebook_citation
Validate a Bluebook legal citation against source document.

**Parameters:** `citation` (str), `document_html` (str, optional).

**Returns:** `{"valid": bool, "errors": [...], "suggestions": [...]}`.

---

## Logic Tools

Temporal-deontic first-order logic (TDFOL) and theorem proving.

### parse_formula
Parse a TDFOL formula string into an AST.

**Parameters:** `formula` (str), `syntax` (str, optional — `"tdfol"` | `"prolog"` | `"tptp"`).

**Returns:** `{"ast": {...}, "valid": bool}`.

### prove_theorem
Attempt to prove a TDFOL theorem.

**Parameters:** `hypothesis` (str), `axioms` (list[str]), `strategy` (str, optional).

**Returns:** `{"proved": bool, "proof_tree": {...}, "steps": int}`.

### check_consistency
Check if a set of formulae is logically consistent.

**Parameters:** `formulae` (list[str]).

**Returns:** `{"consistent": bool}`.

---

## Media Tools

FFmpeg-based video/audio processing and yt-dlp media downloading.

### ffmpeg_convert
Convert a media file to a different format.

**Parameters:** `input_path` (str), `output_path` (str), `codec` (str, optional).

**Returns:** `{"status": "success", "output_path": "..."}`.

### ffmpeg_extract_audio
Extract audio stream from a video file.

**Parameters:** `input_path` (str), `output_path` (str), `audio_format` (str, optional — `"mp3"` | `"wav"`).

**Returns:** `{"status": "success", "output_path": "..."}`.

### yt_dlp_download
Download a video/audio from a URL (1000+ supported platforms).

**Parameters:** `url` (str), `output_dir` (str, optional), `format` (str, optional).

**Returns:** `{"status": "success", "file_path": "...", "title": "..."}`.

---

## Medical Research Scrapers

Biomedical literature retrieval and clinical trial data.

### scrape_pubmed
Retrieve PubMed abstracts for a query.

**Parameters:** `query` (str), `max_results` (int, optional, default 20).

**Returns:** `{"articles": [...], "count": int}`.

### run_clinical_trials
Retrieve clinical trial records from ClinicalTrials.gov.

**Parameters:** `condition` (str), `status` (str, optional).

**Returns:** `{"trials": [...]}`.

---

## PDF Tools

PDF ingestion, text extraction, and GraphRAG relationship analysis.

### pdf_to_text
Extract text from a PDF file.

**Parameters:** `file_path` (str), `page_range` (str, optional — e.g. `"1-10"`).

**Returns:** `{"text": "...", "page_count": int, "metadata": {...}}`.

### pdf_analyze_relationships
Run GraphRAG entity-relationship analysis on a PDF.

**Parameters:** `file_path` (str), `extract_tables` (bool, optional), `extract_images` (bool, optional).

**Returns:** `{"entities": [...], "relationships": [...], "summary": "..."}`.

### pdf_batch_process
Process multiple PDFs in parallel.

**Parameters:** `file_paths` (list[str]), `operations` (list[str], optional).

**Returns:** `{"results": [...], "processed": int, "failed": int}`.

---

## P2P Workflow Tools

Submit and monitor distributed peer-to-peer workflow execution.

### submit_p2p_workflow
**Parameters:** `workflow_type` (str), `params` (dict), `replication` (int, optional, default 1).

**Returns:** `{"workflow_id": "...", "status": "queued"}`.

### get_p2p_workflow_status
**Parameters:** `workflow_id` (str).

**Returns:** `{"status": "running|completed|failed", "progress": float}`.

---

## Rate Limiting Tools

Token-bucket and sliding-window rate enforcement.

### check_rate_limit
**Parameters:** `client_id` (str), `action` (str), `tokens_required` (int, optional, default 1).

**Returns:** `{"allowed": bool, "remaining_tokens": int, "reset_at": "..."}`.

### consume_token
Deduct tokens from a client's bucket.

**Parameters:** `client_id` (str), `action` (str), `tokens` (int, optional, default 1).

**Returns:** `{"status": "success", "remaining": int}`.

---

## Search Tools

Semantic, keyword, and hybrid search over indexed datasets.

### search
General search entry point.

**Parameters:** `query` (str), `index_name` (str), `search_type` (str — `"keyword"` | `"semantic"` | `"hybrid"`), `max_results` (int, optional, default 10).

**Returns:** `{"results": [{"id": "...", "score": float, "text": "...", "metadata": {...}}]}`.

### semantic_search
Pure vector semantic search.

**Parameters:** `query` (str), `index_name` (str), `top_k` (int, optional), `threshold` (float, optional).

**Returns:** `{"results": [...]}`.

### hybrid_search
Combines keyword and semantic scores.

**Parameters:** `query` (str), `index_name` (str), `vector_weight` (float, optional, default 0.5), `max_results` (int, optional).

**Returns:** `{"results": [...]}`.

---

## Security Tools

Access control and permission checking.

### check_access_permission
Check if a principal has permission to perform an action on a resource.

**Parameters:**
- `principal` (str, required) — User/service identifier.
- `action` (str, required) — `"dataset.read"` | `"dataset.write"` | `"ipfs.pin"` | etc.
- `resource` (str, required) — Resource identifier.
- `context` (dict, optional) — Session/IP context.

**Returns:** `{"allowed": bool, "reason": "...", "policy": "..."}`.

---

## Session Tools

User session lifecycle management.

### create_session
**Parameters:** `user_id` (str), `metadata` (dict, optional).

**Returns:** `{"session_id": "...", "expires_at": "..."}`.

### validate_session
**Parameters:** `session_id` (str).

**Returns:** `{"valid": bool, "user_id": "...", "expires_at": "..."}`.

### terminate_session
**Parameters:** `session_id` (str).

**Returns:** `{"terminated": true}`.

---

## Software Engineering Tools

Code review, documentation generation, and project scaffolding.

### code_review
Run automated code review with pattern matching and best-practice checks.

**Parameters:** `file_path` (str), `language` (str, optional), `rules` (list[str], optional).

**Returns:** `{"issues": [...], "severity_summary": {"high": int, "medium": int, "low": int}}`.

### generate_docstring
Auto-generate docstrings for Python functions in a file.

**Parameters:** `file_path` (str), `style` (str, optional — `"google"` | `"numpy"` | `"pep257"`).

**Returns:** `{"updated_file": "...", "functions_documented": int}`.

---

## Sparse Embedding Tools

Sparse vector representations for BM25-style retrieval.

### create_sparse_embedding
Generate a sparse TF-IDF or BM25 embedding.

**Parameters:** `text` (str | list[str]), `model` (str, optional — `"bm25"` | `"tfidf"`).

**Returns:** `{"indices": [int, ...], "values": [float, ...], "dimension": int}`.

---

## Vector Store Tools

High-level CRUD operations over vector stores (FAISS, Qdrant, Elasticsearch).

### vector_index
Add a vector to a named store.

**Parameters:** `store_name` (str), `vector_id` (str), `vector` (list[float]), `metadata` (dict, optional).

**Returns:** `{"status": "success"}`.

### vector_search
ANN search in a named vector store.

**Parameters:** `store_name` (str), `query_vector` (list[float]), `top_k` (int, optional, default 10).

**Returns:** `{"results": [{"id": "...", "score": float, "metadata": {...}}]}`.

### vector_delete
**Parameters:** `store_name` (str), `vector_id` (str).

**Returns:** `{"deleted": true}`.

---

## Web Scraping Tools

General-purpose web scraping and page archiving.

### scrape_url
Fetch and parse a web page, returning structured content.

**Parameters:** `url` (str), `extract_links` (bool, optional), `extract_images` (bool, optional).

**Returns:** `{"html": "...", "text": "...", "title": "...", "links": [...]}`.

### scrape_urls
Bulk URL scraping with concurrency control.

**Parameters:** `urls` (list[str]), `concurrency` (int, optional, default 5).

**Returns:** `{"results": [...], "success_count": int, "failed": [...]}`.

---

## Workflow Tools

Local (non-P2P) workflow orchestration and DAG execution.

### create_workflow
Define a named multi-step workflow.

**Parameters:** `name` (str), `steps` (list[dict — {tool, params, depends_on}]).

**Returns:** `{"workflow_id": "...", "step_count": int}`.

### execute_workflow
Run a previously defined workflow.

**Parameters:** `workflow_id` (str), `inputs` (dict, optional).

**Returns:** `{"status": "success", "results": {...}, "execution_time_ms": float}`.

---

*This reference is auto-generated from tool docstrings and the
`THIN_TOOL_ARCHITECTURE.md` design document.  See individual source files
under `ipfs_datasets_py/mcp_server/tools/` for full parameter details.*
