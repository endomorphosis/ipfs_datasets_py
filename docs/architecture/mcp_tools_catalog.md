# MCP Tools Catalog & Quick Reference

## Tool Inventory

This document provides a comprehensive catalog of all available MCP tools, organized by category with quick reference information for each tool.

**Total Tools Available**: 130+

---

## Quick Reference Index

### Core Operations
- [Dataset Tools](#dataset-tools) (6 tools)
- [IPFS Tools](#ipfs-tools) (6 tools)
- [Vector Tools](#vector-tools) (10 tools)
- [Embedding Tools](#embedding-tools) (15 tools)

### Advanced Operations
- [Analysis Tools](#analysis-tools) (8 tools)
- [Workflow Tools](#workflow-tools) (12 tools)
- [Session Tools](#session-tools) (6 tools)
- [Monitoring Tools](#monitoring-tools) (15 tools)

### System & Admin
- [Security & Auth Tools](#security--auth-tools) (8 tools)
- [Admin Tools](#admin-tools) (8 tools)
- [Cache Tools](#cache-tools) (6 tools)
- [Storage Tools](#storage-tools) (8 tools)

### Specialized Operations
- [Background Task Tools](#background-task-tools) (8 tools)
- [Data Processing Tools](#data-processing-tools) (6 tools)
- [Sparse Embedding Tools](#sparse-embedding-tools) (8 tools)
- [Rate Limiting Tools](#rate-limiting-tools) (4 tools)

### Utilities & Support
- [Audit Tools](#audit-tools) (4 tools)
- [CLI Tools](#cli-tools) (3 tools)
- [Graph Tools](#graph-tools) (3 tools)
- [Provenance Tools](#provenance-tools) (4 tools)
- [Index Management Tools](#index-management-tools) (8 tools)
- [Development Tools](#development-tools) (12 tools)
- [IPFS Cluster Tools](#ipfs-cluster-tools) (8 tools)

---

## Dataset Tools

### Core Dataset Operations

| Tool | Purpose | Key Parameters | Returns |
|------|---------|---------------|---------|
| `load_dataset` | Load datasets from various sources | `source`, `format`, `options` | Dataset ID, metadata, summary |
| `save_dataset` | Save datasets to destinations | `dataset_data`, `destination`, `format` | Save status, location, size |
| `process_dataset` | Apply transformations and operations | `dataset_source`, `operations` | Processed dataset ID, results |
| `convert_dataset_format` | Convert between data formats | `dataset_id`, `target_format` | Conversion status, output info |

**Quick Usage**:
```python
# Load HuggingFace dataset
result = await load_dataset("squad", options={"split": "train"})

# Process with operations
result = await process_dataset(dataset_id, [
    {"type": "filter", "column": "score", "condition": "greater_than", "value": 0.8}
])

# Save to file
result = await save_dataset(dataset_id, "/output/data.parquet", format="parquet")
```

---

## IPFS Tools

### Content Storage & Retrieval

| Tool | Purpose | Key Parameters | Returns |
|------|---------|---------------|---------|
| `pin_to_ipfs` | Store content on IPFS | `content_source`, `recursive`, `hash_algo` | CID, pin status |
| `get_from_ipfs` | Retrieve content by CID | `cid`, `output_path`, `timeout_seconds` | Content info, retrieval status |

---

## IPFS Cluster Tools

### Distributed IPFS Operations

| Tool | Purpose | Key Parameters | Returns |
|------|---------|---------------|---------|
| `get_cluster_status` | Monitor cluster health and nodes | None | Cluster status, node information |
| `add_node` | Add new nodes to cluster | `node_config` | Node addition status |
| `remove_node` | Remove nodes from cluster | `node_id` | Node removal status |
| `pin_content` | Pin content across cluster | `cid`, `replication_factor` | Cluster pin status |
| `unpin_content` | Remove content from cluster | `cid` | Cluster unpin status |
| `list_pins` | List all cluster pins | `status_filter` | Pinned content list |
| `sync_cluster` | Synchronize cluster state | None | Sync status and results |
| `monitor_cluster_health` | Monitor cluster health | `detailed_metrics` | Health metrics and alerts |

**Quick Usage**:
```python
# Check cluster status
status = await get_cluster_status()

# Pin content with replication
result = await pin_content("QmHash123", replication_factor=3)

# Monitor cluster health
health = await monitor_cluster_health(detailed_metrics=True)
```

---

## Vector Tools

### Vector Index Management

| Tool | Purpose | Key Parameters | Returns |
|------|---------|---------------|---------|
| `create_vector_index` | Create vector search index | `vectors`, `metric`, `metadata` | Index ID, configuration |
| `search_vector_index` | Search vector similarity | `index_id`, `query_vector`, `top_k` | Search results, similarities |
| `list_vector_indexes` | List available indexes | `backend` | Index list, metadata |
| `delete_vector_index` | Remove vector index | `index_id`, `backend` | Deletion status |

### Advanced Vector Operations

| Tool | Purpose | Key Parameters | Returns |
|------|---------|---------------|---------|
| `create_vector_index` (multi-backend) | Multi-backend index creation | `backend`, `dimension`, `metric` | Backend-specific index |
| `_create_faiss_index` | FAISS-specific indexing | `vectors`, `index_type` | FAISS index configuration |
| `_create_qdrant_index` | Qdrant vector database | `collection_name`, `vector_config` | Qdrant collection info |
| `_create_elasticsearch_index` | Elasticsearch vectors | `index_name`, `mapping` | ES index configuration |

**Quick Usage**:
```python
# Create index
result = await create_vector_index(
    vectors=[[0.1, 0.2], [0.3, 0.4]], 
    metric="cosine"
)

# Search similar vectors
result = await search_vector_index(
    index_id="idx_123", 
    query_vector=[0.15, 0.25], 
    top_k=5
)
```

---

## Embedding Tools

### Core Embedding Generation

| Tool | Purpose | Key Parameters | Returns |
|------|---------|---------------|---------|
| `create_embeddings` | Generate embeddings | `texts`, `model`, `endpoint_type` | Embeddings, metadata |
| `generate_embedding` | Single text embedding | `text`, `model`, `normalize` | Single embedding vector |
| `generate_batch_embeddings` | Batch embedding generation | `texts`, `model`, `batch_size` | Batch embeddings, stats |
| `generate_embeddings_from_file` | File-based embedding | `file_path`, `model`, `chunk_strategy` | File embeddings, info |

### Advanced Embedding Operations

| Tool | Purpose | Key Parameters | Returns |
|------|---------|---------------|---------|
| `index_dataset` | Dataset embedding & indexing | `dataset_id`, `text_column`, `model` | Indexed dataset info |
| `search_embeddings` | Semantic search | `query`, `index_id`, `filters` | Search results, scores |
| `chunk_text` | Text chunking | `text`, `strategy`, `chunk_size` | Text chunks, boundaries |
| `manage_endpoints` | Endpoint configuration | `action`, `endpoint_config` | Endpoint status |

### Embedding Search & Retrieval

| Tool | Purpose | Key Parameters | Returns |
|------|---------|---------------|---------|
| `semantic_search` | Semantic similarity search | `query`, `index_id`, `top_k` | Semantic results |
| `multi_modal_search` | Multi-modal search | `query`, `modalities`, `weights` | Multi-modal results |
| `hybrid_search` | Semantic + keyword search | `query`, `keyword_weight`, `semantic_weight` | Hybrid results |
| `search_with_filters` | Filtered semantic search | `query`, `filters`, `metadata_filters` | Filtered results |

**Quick Usage**:
```python
# Generate embeddings
result = await create_embeddings(
    texts=["Hello world", "AI is amazing"],
    model="thenlper/gte-small"
)

# Semantic search
result = await semantic_search(
    query="machine learning",
    index_id="embeddings_idx",
    top_k=10
)
```

---

## Analysis Tools

### Data Analysis & ML

| Tool | Purpose | Key Parameters | Returns |
|------|---------|---------------|---------|
| `cluster_analysis` | Data clustering | `data`, `algorithm`, `n_clusters` | Clusters, centroids, metrics |
| `quality_assessment` | Data quality analysis | `data`, `metrics`, `thresholds` | Quality scores, issues |
| `dimensionality_reduction` | Reduce data dimensions | `data`, `method`, `target_dimensions` | Reduced data, variance |
| `analyze_data_distribution` | Statistical distribution | `data`, `columns`, `bins` | Distribution stats |

**Quick Usage**:
```python
# Cluster embeddings
result = await cluster_analysis(
    data=embedding_vectors,
    algorithm="kmeans",
    n_clusters=5
)

# Assess data quality
result = await quality_assessment(
    data=dataset,
    metrics=["completeness", "consistency"]
)
```

---

## Workflow Tools

### Workflow Orchestration

| Tool | Purpose | Key Parameters | Returns |
|------|---------|---------------|---------|
| `execute_workflow` | Execute multi-step workflows | `workflow_definition`, `context` | Workflow results |
| `batch_process_datasets` | Batch dataset processing | `datasets`, `pipeline` | Batch results |
| `schedule_workflow` | Schedule future workflows | `workflow`, `schedule`, `trigger` | Schedule status |
| `get_workflow_status` | Monitor workflow progress | `workflow_id` | Status, progress |

### Workflow Step Executors

| Tool | Purpose | Key Parameters | Returns |
|------|---------|---------------|---------|
| `_execute_embedding_step` | Embedding workflow step | `params`, `context` | Step results |
| `_execute_dataset_step` | Dataset workflow step | `params`, `context` | Step results |
| `_execute_vector_step` | Vector workflow step | `params`, `context` | Step results |
| `_execute_ipfs_step` | IPFS workflow step | `params`, `context` | Step results |
| `_execute_conditional_step` | Conditional logic step | `params`, `context` | Conditional results |
| `_execute_parallel_step` | Parallel execution step | `params`, `context` | Parallel results |

**Quick Usage**:
```python
# Execute workflow
workflow = {
    "steps": [
        {"type": "dataset_processing", "parameters": {...}},
        {"type": "embedding_generation", "parameters": {...}}
    ]
}
result = await execute_workflow(workflow)
```

---

## Session Tools

### Session Management

| Tool | Purpose | Key Parameters | Returns |
|------|---------|---------------|---------|
| `create_session` | Create user session | `session_name`, `user_id`, `config` | Session ID, info |
| `manage_session_state` | Manage session state | `session_id`, `action`, `data` | State update status |
| `cleanup_sessions` | Clean expired sessions | `cleanup_type`, `user_id` | Cleanup results |

**Quick Usage**:
```python
# Create session
result = await create_session(
    session_name="analysis_session",
    user_id="user123"
)

# Manage state
result = await manage_session_state(
    session_id="sess_123",
    action="update",
    data={"current_dataset": "data_456"}
)
```

---

## Monitoring Tools

### System Health & Performance

| Tool | Purpose | Key Parameters | Returns |
|------|---------|---------------|---------|
| `health_check` | System health monitoring | `components`, `include_details` | Health status, scores |
| `get_performance_metrics` | Performance metrics | `time_range`, `components` | Metrics, trends |
| `monitor_services` | Service monitoring | `services`, `check_interval` | Service statuses |
| `generate_monitoring_report` | Monitoring reports | `report_type`, `time_range` | Report data |

### Component Health Checks

| Tool | Purpose | Key Parameters | Returns |
|------|---------|---------------|---------|
| `_check_system_health` | System resource health | None | System health data |
| `_check_memory_health` | Memory usage health | None | Memory health data |
| `_check_cpu_health` | CPU usage health | None | CPU health data |
| `_check_disk_health` | Disk usage health | None | Disk health data |
| `_check_network_health` | Network connectivity | None | Network health data |
| `_check_services_health` | Service availability | None | Services health data |
| `_check_embeddings_health` | Embeddings service health | None | Embeddings health |
| `_check_vector_stores_health` | Vector DB health | None | Vector stores health |

**Quick Usage**:
```python
# Comprehensive health check
result = await health_check(
    components=["system", "services", "embeddings"],
    include_details=True
)

# Performance monitoring
result = await get_performance_metrics(
    time_range="1h",
    components=["cpu", "memory"]
)
```

---

## Security & Auth Tools

### Authentication & Authorization

| Tool | Purpose | Key Parameters | Returns |
|------|---------|---------------|---------|
| `check_access_permission` | Check user permissions | `resource_id`, `user_id`, `permission_type` | Permission status |
| `authenticate_user` | User authentication | `username`, `password`, `auth_service` | Auth result, token |
| `validate_token` | Token validation | `token`, `required_permission` | Validation result |
| `get_user_info` | User information | `token`, `auth_service` | User data, permissions |

**Quick Usage**:
```python
# Check permissions
result = await check_access_permission(
    resource_id="dataset_123",
    user_id="user456",
    permission_type="read"
)

# Authenticate user
result = await authenticate_user(
    username="john_doe",
    password="secure_password"
)
```

---

## Admin Tools

### System Administration

| Tool | Purpose | Key Parameters | Returns |
|------|---------|---------------|---------|
| `manage_endpoints` | Endpoint management | `action`, `endpoint_config`, `endpoint_id` | Management result |
| `system_maintenance` | System maintenance | `action`, `components`, `schedule` | Maintenance status |
| `configure_system` | System configuration | `config_type`, `settings`, `scope` | Configuration status |

**Quick Usage**:
```python
# Add endpoint
result = await manage_endpoints(
    action="add",
    endpoint_config={
        "name": "tei-server",
        "url": "http://tei:8080",
        "type": "embedding"
    }
)

# System maintenance
result = await system_maintenance(
    action="cleanup",
    components=["cache", "temp_files"]
)
```

---

## Cache Tools

### Caching & Optimization

| Tool | Purpose | Key Parameters | Returns |
|------|---------|---------------|---------|
| `manage_cache` | Cache operations | `operation`, `cache_type`, `key`, `value` | Cache result |
| `optimize_cache` | Cache optimization | `strategy`, `target_size`, `eviction_policy` | Optimization result |
| `cache_embeddings` | Cache embedding results | `embeddings`, `cache_key`, `ttl` | Cache status |
| `get_cached_embeddings` | Retrieve cached embeddings | `cache_key`, `model`, `text_hash` | Cached embeddings |

**Quick Usage**:
```python
# Cache embeddings
result = await cache_embeddings(
    embeddings=embedding_vectors,
    cache_key="doc_embeddings_v1",
    ttl=3600
)

# Get cached data
result = await get_cached_embeddings(
    cache_key="doc_embeddings_v1"
)
```

---

## Storage Tools

### Advanced Storage Operations

| Tool | Purpose | Key Parameters | Returns |
|------|---------|---------------|---------|
| `store_data` | Store data in backends | `data`, `storage_type`, `location` | Storage result |
| `retrieve_data` | Retrieve stored data | `storage_id`, `storage_type`, `filters` | Retrieved data |
| `manage_collections` | Collection management | `action`, `collection_name`, `metadata` | Collection status |
| `query_storage` | Query stored data | `query`, `storage_type`, `filters` | Query results |

**Quick Usage**:
```python
# Store data
result = await store_data(
    data=dataset,
    storage_type="object_store",
    location="datasets/processed"
)

# Query storage
result = await query_storage(
    query={"category": "science"},
    storage_type="document_store"
)
```

---

## Background Task Tools

### Asynchronous Task Management

| Tool | Purpose | Key Parameters | Returns |
|------|---------|---------------|---------|
| `check_task_status` | Check task progress | `task_id`, `task_type` | Task status, progress |
| `manage_background_tasks` | Task lifecycle management | `action`, `task_id`, `task_config` | Management result |
| `manage_task_queue` | Queue management | `action`, `priority`, `max_workers` | Queue status |

**Quick Usage**:
```python
# Start background task
result = await manage_background_tasks(
    action="start",
    task_config={
        "type": "embedding_generation",
        "data": large_dataset,
        "priority": "high"
    }
)

# Check task status
result = await check_task_status(task_id="task_123")
```

---

## Data Processing Tools

### Text & Data Processing

| Tool | Purpose | Key Parameters | Returns |
|------|---------|---------------|---------|
| `chunk_text` | Text chunking | `text`, `strategy`, `chunk_size`, `overlap` | Text chunks |
| `transform_data` | Data transformation | `data`, `transformation`, `parameters` | Transformed data |
| `convert_format` | Format conversion | `data`, `source_format`, `target_format` | Converted data |
| `validate_data` | Data validation | `data`, `validation_type`, `schema` | Validation results |

**Quick Usage**:
```python
# Chunk text
result = await chunk_text(
    text=long_document,
    strategy="sentence",
    chunk_size=512,
    overlap=50
)

# Transform data
result = await transform_data(
    data=dataset,
    transformation="normalize",
    parameters={"method": "z_score"}
)
```

---

## Sparse Embedding Tools

### Sparse Vector Operations

| Tool | Purpose | Key Parameters | Returns |
|------|---------|---------------|---------|
| `generate_sparse_embedding` | Sparse embedding generation | `text`, `model`, `sparsity_factor` | Sparse embeddings |
| `index_sparse_collection` | Sparse collection indexing | `embeddings`, `metadata`, `index_config` | Sparse index |
| `sparse_search` | Sparse vector search | `query`, `index_id`, `top_k` | Sparse search results |
| `manage_sparse_models` | Sparse model management | `action`, `model_config` | Model management result |

**Quick Usage**:
```python
# Generate sparse embeddings
result = await generate_sparse_embedding(
    text="sample text",
    model="splade",
    sparsity_factor=0.1
)

# Search sparse index
result = await sparse_search(
    query="search query",
    index_id="sparse_idx_123",
    top_k=10
)
```

---

## Rate Limiting Tools

### Traffic Control & Throttling

| Tool | Purpose | Key Parameters | Returns |
|------|---------|---------------|---------|
| `configure_rate_limits` | Configure rate limits | `limits`, `scope`, `enforcement` | Configuration status |
| `check_rate_limit` | Check rate limit status | `user_id`, `resource`, `action` | Rate limit status |
| `manage_rate_limits` | Rate limit management | `action`, `limit_id`, `config` | Management result |

**Quick Usage**:
```python
# Configure limits
result = await configure_rate_limits(
    limits={"embedding_api": {"requests_per_minute": 100}},
    scope="user"
)

# Check limit
result = await check_rate_limit(
    user_id="user123",
    resource="embedding_api"
)
```

---

## Audit Tools

### Compliance & Audit

| Tool | Purpose | Key Parameters | Returns |
|------|---------|---------------|---------|
| `generate_audit_report` | Audit report generation | `report_type`, `time_range`, `filters` | Audit report |
| `record_audit_event` | Record audit events | `action`, `resource_id`, `user_id` | Event record |

**Quick Usage**:
```python
# Generate audit report
result = await generate_audit_report(
    report_type="security",
    time_range="last_30_days"
)

# Record event
result = await record_audit_event(
    action="dataset_access",
    resource_id="dataset_123",
    user_id="user456"
)
```

---

## CLI Tools

### Command-Line Operations

| Tool | Purpose | Key Parameters | Returns |
|------|---------|---------------|---------|
| `execute_command` | Execute CLI commands | `command`, `working_dir`, `timeout` | Command output |

**Quick Usage**:
```python
# Execute command
result = await execute_command(
    command="ls -la /data",
    working_dir="/app",
    timeout=30
)
```

---

## Graph Tools

### Knowledge Graph Operations

| Tool | Purpose | Key Parameters | Returns |
|------|---------|---------------|---------|
| `query_knowledge_graph` | Graph querying | `graph_id`, `query`, `query_type` | Query results |

**Quick Usage**:
```python
# Query graph
result = await query_knowledge_graph(
    graph_id="kg_123",
    query="SELECT * WHERE { ?s ?p ?o }",
    query_type="sparql"
)
```

---

## Provenance Tools

### Data Lineage & Tracking

| Tool | Purpose | Key Parameters | Returns |
|------|---------|---------------|---------|
| `record_provenance` | Record data lineage | `dataset_id`, `operation`, `inputs` | Provenance record |

**Quick Usage**:
```python
# Record provenance
result = await record_provenance(
    dataset_id="dataset_123",
    operation="transformation",
    inputs=["source_dataset_456"]
)
```

---

## Index Management Tools

### Index Lifecycle Management

| Tool | Purpose | Key Parameters | Returns |
|------|---------|---------------|---------|
| `load_index` | Load index into memory | `index_id`, `cache_config` | Load status |
| `manage_shards` | Shard management | `action`, `shard_config` | Shard operation result |
| `monitor_index_status` | Index health monitoring | `index_id`, `check_type` | Index status |
| `manage_index_configuration` | Index configuration | `index_id`, `config_updates` | Configuration result |

**Quick Usage**:
```python
# Load index
result = await load_index(
    index_id="idx_123",
    cache_config={"memory_limit": "2GB"}
)

# Monitor index
result = await monitor_index_status(
    index_id="idx_123",
    check_type="performance"
)
```

---

## Tool Integration Examples

### Common Workflows

**Data Ingestion**: `load_dataset` → `process_dataset` → `convert_dataset_format`

**Semantic Search**: `generate_embedding` → `create_vector_index` → `search_vector_index`

**Large-Scale Processing**: `execute_workflow` → `batch_process_datasets` → `manage_background_tasks`

**System Monitoring**: `health_check` → `get_performance_metrics` → `generate_audit_report`

**Data Storage**: `pin_to_ipfs` → `store_data` → `record_provenance`

**Distributed Operations**: `get_cluster_status` → `pin_content` → `sync_cluster`

### Performance Optimization

**Batch Operations**: Use batch tools for multiple items
**Caching**: Enable caching for frequent operations  
**Monitoring**: Regular health checks and performance metrics
**Scaling**: Use cluster tools for distributed operations

This catalog provides quick access to all available tools with essential information for rapid integration and development.
