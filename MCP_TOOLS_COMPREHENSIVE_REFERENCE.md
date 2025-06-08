# MCP Tools Comprehensive Reference Guide

## Overview

This document provides comprehensive documentation for all 100+ MCP (Model Context Protocol) tools available in the `ipfs_datasets_py` project. These tools enable AI assistants to interact with IPFS datasets, embeddings, vector stores, and related infrastructure through a standardized interface.

## Table of Contents

1. [Tool Categories](#tool-categories)
2. [Core Dataset Tools](#core-dataset-tools)
3. [IPFS Tools](#ipfs-tools)
4. [Embedding Tools](#embedding-tools)
5. [Vector Store Tools](#vector-store-tools)
6. [Analytics Tools](#analytics-tools)
7. [Workflow Tools](#workflow-tools)
8. [Monitoring Tools](#monitoring-tools)
9. [Security & Authentication Tools](#security--authentication-tools)
10. [Administrative Tools](#administrative-tools)
11. [Development Tools](#development-tools)
12. [Specialized Tools](#specialized-tools)
13. [Usage Examples](#usage-examples)
14. [Best Practices](#best-practices)

---

## Tool Categories

The MCP tools are organized into the following categories for easy discovery and management:

| Category | Count | Purpose |
|----------|--------|---------|
| Dataset Tools | 15+ | Dataset loading, processing, conversion, and management |
| IPFS Tools | 10+ | IPFS operations, pinning, retrieval, and cluster management |
| Embedding Tools | 20+ | Embedding generation, management, and optimization |
| Vector Store Tools | 15+ | Vector indexing, search, and store management |
| Analytics Tools | 10+ | Data analysis, clustering, quality assessment |
| Workflow Tools | 8+ | Workflow execution, task orchestration, scheduling |
| Monitoring Tools | 12+ | System monitoring, health checks, performance metrics |
| Security Tools | 8+ | Authentication, authorization, access control |
| Admin Tools | 10+ | System administration, configuration management |
| Development Tools | 15+ | Testing, linting, documentation generation |

---

## Core Dataset Tools

### Dataset Management

#### 1. `load_dataset`
**Purpose**: Load datasets from various sources including Hugging Face Hub, local files, URLs.

**Function**: `mcp_ipfs-datasets2_load_dataset`

**Parameters**:
- `source` (required): Dataset source (HF dataset name, file path, URL)
- `format` (optional): Dataset format (json, csv, parquet, text)
- `options` (optional): Additional loading options (split, streaming, etc.)

**Returns**:
- `status`: "success" or "error"
- `dataset_id`: Unique identifier for loaded dataset
- `metadata`: Dataset metadata including features and description
- `summary`: Record count, schema, source, and format information

**Example Usage**:
```python
# Load from Hugging Face
result = await load_dataset("squad", format="json")

# Load local file
result = await load_dataset("/path/to/data.csv", format="csv")

# Load with options
result = await load_dataset("glue/mnli", options={"split": "train", "streaming": True})
```

#### 2. `process_dataset`
**Purpose**: Apply transformations, filters, and operations to datasets.

**Function**: `mcp_ipfs-datasets2_process_dataset`

**Parameters**:
- `dataset_source` (required): Dataset ID or data dictionary
- `operations` (required): List of operation dictionaries
- `output_id` (optional): ID for resulting dataset

**Operations Supported**:
- `filter`: Apply filters based on conditions
- `map`: Transform data with functions
- `select`: Select specific columns
- `sort`: Sort by columns
- `group`: Group by fields
- `aggregate`: Perform aggregations

**Example Usage**:
```python
operations = [
    {"type": "filter", "column": "text", "condition": "length > 100"},
    {"type": "select", "columns": ["id", "text", "label"]},
    {"type": "sort", "column": "id", "ascending": True}
]
result = await process_dataset("dataset_123", operations)
```

#### 3. `save_dataset`
**Purpose**: Save datasets to various destinations and formats.

**Function**: `mcp_ipfs-datasets2_save_dataset`

**Parameters**:
- `dataset_data` (required): Dataset ID or content dictionary
- `destination` (required): Save destination path
- `format` (optional): Output format (json, csv, parquet, arrow, car)
- `options` (optional): Additional save options

**Example Usage**:
```python
result = await save_dataset("dataset_123", "/path/to/output.json", format="json")
```

#### 4. `convert_dataset_format`
**Purpose**: Convert datasets between different formats.

**Function**: `mcp_ipfs-datasets2_convert_dataset_format`

**Parameters**:
- `dataset_id` (required): ID of dataset to convert
- `target_format` (required): Target format
- `output_path` (optional): Save location
- `options` (optional): Conversion options

---

## IPFS Tools

### Basic IPFS Operations

#### 1. `pin_to_ipfs`
**Purpose**: Pin files, directories, or data to IPFS network.

**Function**: `mcp_ipfs-datasets2_pin_to_ipfs`

**Parameters**:
- `content_source` (required): File path, directory, or data dictionary
- `recursive` (optional): Add directory recursively (default: true)
- `wrap_with_directory` (optional): Wrap files in directory (default: false)
- `hash_algo` (optional): Hash algorithm (default: "sha2-256")

**Returns**:
- `status`: Operation status
- `cid`: Content Identifier (CID) of pinned content
- `size`: Size information
- `hash`: Hash details

#### 2. `get_from_ipfs`
**Purpose**: Retrieve content from IPFS by CID.

**Function**: `mcp_ipfs-datasets2_get_from_ipfs`

**Parameters**:
- `cid` (required): Content Identifier to retrieve
- `output_path` (optional): Local save location
- `timeout_seconds` (optional): Retrieval timeout (default: 60)

**Returns**:
- `status`: Retrieval status
- `content`: Retrieved content (if no output_path)
- `path`: Local file path (if output_path provided)
- `size`: Content size

### IPFS Cluster Management

#### 3. `cluster_status`
**Purpose**: Get IPFS cluster status and node information.

**Function**: Available through enhanced IPFS cluster tools

**Features**:
- Node health monitoring
- Cluster synchronization status
- Pin distribution analysis
- Performance metrics

#### 4. `cluster_pin_management`
**Purpose**: Manage pinning across IPFS cluster nodes.

**Operations**:
- Add/remove pins
- Set replication factors
- Monitor pin status
- Synchronize cluster state

---

## Embedding Tools

### Embedding Generation

#### 1. `generate_embedding`
**Purpose**: Generate embeddings for single text inputs.

**Function**: Available through embedding generation tools

**Parameters**:
- `text` (required): Input text to embed
- `model` (optional): Embedding model to use
- `normalize` (optional): Normalize embeddings
- `options` (optional): Model-specific options

#### 2. `generate_batch_embeddings`
**Purpose**: Generate embeddings for multiple texts efficiently.

**Parameters**:
- `texts` (required): List of input texts
- `batch_size` (optional): Processing batch size
- `model` (optional): Embedding model
- `parallel` (optional): Enable parallel processing

#### 3. `generate_embeddings_from_file`
**Purpose**: Generate embeddings from file contents.

**Parameters**:
- `file_path` (required): Path to input file
- `chunk_size` (optional): Text chunking size
- `overlap` (optional): Chunk overlap size
- `format` (optional): File format handling

### Advanced Embedding Operations

#### 4. `shard_embeddings_by_dimension`
**Purpose**: Shard large embedding collections by dimensions.

**Function**: `shard_embeddings_by_dimension`

**Use Cases**:
- Memory optimization for large embedding sets
- Distributed processing
- Selective dimension analysis

#### 5. `shard_embeddings_by_cluster`
**Purpose**: Shard embeddings based on clustering results.

**Function**: `shard_embeddings_by_cluster`

**Features**:
- K-means clustering
- Custom distance metrics
- Balanced shard creation

#### 6. `merge_embedding_shards`
**Purpose**: Combine sharded embeddings back into unified collections.

**Function**: `merge_embedding_shards`

### Embedding Search and Management

#### 7. `search_embeddings`
**Purpose**: Perform semantic search across embedding collections.

**Parameters**:
- `query_embedding` or `query_text`: Search query
- `collection_id`: Target embedding collection
- `top_k`: Number of results
- `filters`: Metadata filters
- `threshold`: Similarity threshold

#### 8. `manage_endpoints`
**Purpose**: Manage embedding service endpoints and models.

**Operations**:
- Add/remove endpoints
- Monitor endpoint health
- Load balance requests
- Cache management

---

## Vector Store Tools

### Vector Index Management

#### 1. `create_vector_index`
**Purpose**: Create vector indices for similarity search.

**Function**: `mcp_ipfs-datasets2_create_vector_index`

**Parameters**:
- `vectors` (required): List of vectors to index
- `dimension` (optional): Vector dimensions (auto-detected)
- `metric` (optional): Distance metric (cosine, l2, ip)
- `metadata` (optional): Associated metadata
- `index_id` (optional): Custom index identifier
- `index_name` (optional): Human-readable name

**Returns**:
- `status`: Creation status
- `index_id`: Unique index identifier
- `configuration`: Index configuration details
- `statistics`: Index statistics

#### 2. `search_vector_index`
**Purpose**: Search vector indices for similar items.

**Function**: `mcp_ipfs-datasets2_search_vector_index`

**Parameters**:
- `index_id` (required): Target index ID
- `query_vector` (required): Query vector
- `top_k` (optional): Number of results (default: 5)
- `include_metadata` (optional): Include metadata (default: true)
- `include_distances` (optional): Include distances (default: true)
- `filter_metadata` (optional): Metadata filtering

### Enhanced Vector Operations

#### 3. `vector_store_management`
**Purpose**: Advanced vector store operations and management.

**Operations**:
- Index optimization
- Shard management  
- Performance tuning
- Memory optimization

#### 4. `load_index`
**Purpose**: Load and initialize vector indices from storage.

**Function**: `load_index`

**Features**:
- Lazy loading
- Memory mapping
- Distributed loading
- Version management

---

## Analytics Tools

### Data Analysis

#### 1. `cluster_analysis`
**Purpose**: Perform clustering analysis on datasets and embeddings.

**Function**: `mcp_ipfs-datasets2_cluster_analysis`

**Parameters**:
- `data` (required): Input data for clustering
- `algorithm` (optional): Clustering algorithm (kmeans, dbscan, hierarchical)
- `n_clusters` (optional): Number of clusters
- `features` (optional): Feature selection
- `options` (optional): Algorithm-specific options

**Algorithms Supported**:
- K-Means clustering
- DBSCAN density clustering
- Hierarchical clustering
- Gaussian mixture models

#### 2. `quality_assessment`
**Purpose**: Assess data quality and embedding quality.

**Function**: `mcp_ipfs-datasets2_quality_assessment`

**Metrics**:
- Data completeness
- Embedding coherence
- Cluster quality
- Outlier detection

#### 3. `dimensionality_reduction`
**Purpose**: Reduce dimensionality for visualization and analysis.

**Function**: `mcp_ipfs-datasets2_dimensionality_reduction`

**Techniques**:
- PCA (Principal Component Analysis)
- t-SNE
- UMAP
- Custom projections

#### 4. `analyze_data_distribution`
**Purpose**: Analyze statistical distributions in datasets.

**Function**: `mcp_ipfs-datasets2_analyze_data_distribution`

**Features**:
- Statistical summaries
- Distribution fitting
- Anomaly detection
- Trend analysis

---

## Workflow Tools

### Workflow Management

#### 1. `execute_workflow`
**Purpose**: Execute complex multi-step workflows.

**Function**: Available through workflow tools

**Features**:
- Step-by-step execution
- Error handling and recovery
- Progress tracking
- Resource management

**Workflow Types**:
- Data processing pipelines
- Embedding generation workflows
- Analysis workflows
- Multi-dataset operations

#### 2. `batch_process_datasets`
**Purpose**: Process multiple datasets in batch operations.

**Function**: `batch_process_datasets`

**Parameters**:
- `dataset_configs`: List of dataset configurations
- `pipeline`: Processing pipeline steps
- `parallel`: Enable parallel processing
- `error_handling`: Error handling strategy

#### 3. `schedule_workflow`
**Purpose**: Schedule workflows for future execution.

**Function**: `schedule_workflow`

**Features**:
- Cron-like scheduling
- Resource constraints
- Dependency management
- Monitoring integration

#### 4. `get_workflow_status`
**Purpose**: Monitor workflow execution status.

**Function**: `get_workflow_status`

**Information Provided**:
- Execution progress
- Step completion status
- Error details
- Resource usage
- Estimated completion time

---

## Monitoring Tools

### System Monitoring

#### 1. `health_check`
**Purpose**: Comprehensive system health monitoring.

**Function**: Available through monitoring tools

**Checks**:
- System resources (CPU, memory, disk)
- Service availability
- Network connectivity
- IPFS node status
- Database connections

#### 2. `get_performance_metrics`
**Purpose**: Collect detailed performance metrics.

**Function**: `get_performance_metrics`

**Metrics**:
- Response times
- Throughput rates
- Error rates
- Resource utilization
- Queue lengths

#### 3. `monitor_services`
**Purpose**: Monitor specific service status and performance.

**Function**: `monitor_services`

**Services Monitored**:
- Embedding services
- Vector stores
- IPFS nodes
- Databases
- Web services

#### 4. `generate_monitoring_report`
**Purpose**: Generate comprehensive monitoring reports.

**Function**: `generate_monitoring_report`

**Report Types**:
- System health summaries
- Performance analysis
- Trend reports
- Alert summaries
- Capacity planning

---

## Security & Authentication Tools

### Authentication

#### 1. `authenticate_user`
**Purpose**: Authenticate users with various methods.

**Function**: Available through auth tools

**Methods**:
- Username/password
- Token-based auth
- API key validation
- Multi-factor authentication

#### 2. `validate_token`
**Purpose**: Validate authentication tokens and permissions.

**Function**: Available through auth tools

**Features**:
- Token expiration checking
- Permission validation
- Role-based access control
- Audit logging

#### 3. `check_access_permission`
**Purpose**: Check user permissions for resources.

**Function**: `mcp_ipfs-datasets2_check_access_permission`

**Parameters**:
- `resource_id` (required): Resource identifier
- `user_id` (required): User identifier
- `permission_type` (optional): Permission type (read, write, delete, share)
- `resource_type` (optional): Resource type

### Security Monitoring

#### 4. `security_audit`
**Purpose**: Perform security audits and compliance checks.

**Features**:
- Access pattern analysis
- Permission auditing
- Vulnerability scanning
- Compliance reporting

---

## Administrative Tools

### System Administration

#### 1. `system_configuration`
**Purpose**: Manage system configuration and settings.

**Operations**:
- Configuration updates
- Setting validation
- Backup and restore
- Environment management

#### 2. `user_management`
**Purpose**: Manage user accounts and permissions.

**Features**:
- User creation/deletion
- Role assignment
- Permission management
- Activity monitoring

#### 3. `resource_management`
**Purpose**: Manage system resources and quotas.

**Resources**:
- Storage quotas
- Compute limits
- Network bandwidth
- API rate limits

### Maintenance Operations

#### 4. `cleanup_operations`
**Purpose**: Perform system cleanup and maintenance.

**Operations**:
- Temporary file cleanup
- Log rotation
- Cache clearing
- Garbage collection

#### 5. `backup_restore`
**Purpose**: Backup and restore system data.

**Features**:
- Incremental backups
- Point-in-time recovery
- Cross-region replication
- Disaster recovery

---

## Development Tools

### Testing and Quality Assurance

#### 1. `run_comprehensive_tests`
**Purpose**: Execute comprehensive test suites.

**Function**: `mcp_ipfs-datasets2_run_comprehensive_tests`

**Test Types**:
- Unit tests
- Integration tests
- Performance tests
- Dataset integrity tests

#### 2. `create_test_runner`
**Purpose**: Create and configure test runners.

**Function**: `mcp_ipfs-datasets2_create_test_runner`

**Configuration Options**:
- Test frameworks (pytest, unittest)
- Coverage reporting
- Output formats
- Parallel execution

#### 3. `lint_codebase`
**Purpose**: Perform code quality analysis and linting.

**Features**:
- Style checking
- Error detection
- Best practice validation
- Automated fixing

### Documentation and Code Generation

#### 4. `generate_documentation`
**Purpose**: Generate documentation from code and configurations.

**Output Formats**:
- Markdown
- HTML
- PDF
- API documentation

#### 5. `code_analysis`
**Purpose**: Analyze codebase structure and dependencies.

**Analysis Types**:
- Dependency mapping
- Complexity analysis
- Security scanning
- Performance profiling

---

## Specialized Tools

### Web Archive Tools

#### 1. `create_warc`
**Purpose**: Create Web ARChive (WARC) files.

**Features**:
- Web page archiving
- Metadata preservation
- Compression options
- Standards compliance

#### 2. `extract_text_from_warc`
**Purpose**: Extract text content from WARC files.

**Capabilities**:
- HTML text extraction
- Content filtering
- Language detection
- Format conversion

#### 3. `extract_links_from_warc`
**Purpose**: Extract links and relationships from WARC files.

**Outputs**:
- Link graphs
- Relationship mapping
- Network analysis
- Navigation patterns

### Session Management

#### 4. `create_session`
**Purpose**: Create and manage user sessions.

**Function**: Available through session tools

**Features**:
- Session lifecycle management
- State persistence
- Timeout handling
- Multi-user support

#### 5. `manage_session_state`
**Purpose**: Manage session state and data.

**Operations**:
- State updates
- Data retrieval
- Session cleanup
- State validation

### Provenance and Audit

#### 6. `record_provenance`
**Purpose**: Record data provenance and lineage.

**Function**: `mcp_ipfs-datasets2_record_provenance`

**Parameters**:
- `dataset_id` (required): Dataset identifier
- `operation` (required): Performed operation
- `inputs` (optional): Input sources
- `parameters` (optional): Operation parameters
- `description` (optional): Operation description

#### 7. `record_audit_event`
**Purpose**: Record audit events for compliance and security.

**Function**: `mcp_ipfs-datasets2_record_audit_event`

**Parameters**:
- `action` (required): Action performed
- `resource_id` (optional): Affected resource
- `user_id` (optional): User identifier
- `details` (optional): Additional details
- `severity` (optional): Event severity

#### 8. `generate_audit_report`
**Purpose**: Generate comprehensive audit reports.

**Function**: `mcp_ipfs-datasets2_generate_audit_report`

**Report Types**:
- Security reports
- Compliance reports
- Operational reports
- Comprehensive summaries

---

## Usage Examples

### Common Workflows

#### 1. Dataset Processing Pipeline
```python
# Load dataset
dataset_result = await load_dataset("squad", format="json")
dataset_id = dataset_result["dataset_id"]

# Process dataset
operations = [
    {"type": "filter", "column": "context", "condition": "length > 100"},
    {"type": "select", "columns": ["question", "context", "answers"]}
]
processed_result = await process_dataset(dataset_id, operations)

# Generate embeddings
embedding_result = await generate_embeddings_from_dataset(processed_result["dataset_id"])

# Create vector index
index_result = await create_vector_index(
    vectors=embedding_result["embeddings"],
    metric="cosine",
    index_name="squad_embeddings"
)

# Save results
await save_dataset(processed_result["dataset_id"], "/output/processed_squad.json")
```

#### 2. Search and Analysis Workflow
```python
# Search vector index
search_results = await search_vector_index(
    index_id="squad_embeddings",
    query_vector=query_embedding,
    top_k=10,
    include_metadata=True
)

# Analyze results
cluster_results = await cluster_analysis(
    data=search_results["results"],
    algorithm="kmeans",
    n_clusters=3
)

# Generate quality assessment
quality_results = await quality_assessment(
    data=search_results["results"],
    metrics=["coherence", "diversity", "coverage"]
)
```

#### 3. IPFS Integration Workflow
```python
# Pin dataset to IPFS
pin_result = await pin_to_ipfs(
    content_source="/path/to/dataset.json",
    recursive=True
)

# Record provenance
provenance_result = await record_provenance(
    dataset_id="dataset_123",
    operation="ipfs_pin",
    parameters={"cid": pin_result["cid"]}
)

# Create audit record
audit_result = await record_audit_event(
    action="dataset.publish",
    resource_id="dataset_123",
    details={"cid": pin_result["cid"], "size": pin_result["size"]}
)
```

---

## Best Practices

### Tool Usage Guidelines

1. **Error Handling**: Always check the `status` field in tool responses
2. **Resource Management**: Use appropriate timeouts and limits
3. **Security**: Validate inputs and check permissions
4. **Performance**: Use batch operations for large datasets
5. **Monitoring**: Track tool usage and performance metrics

### Common Patterns

#### Async Execution
All tools are async functions that should be awaited:
```python
result = await tool_function(parameters)
```

#### Error Response Format
```python
{
    "status": "error",
    "message": "Error description",
    "error_code": "ERROR_CODE",
    "details": {}
}
```

#### Success Response Format
```python
{
    "status": "success",
    "data": {},
    "metadata": {},
    "execution_time": 1.23
}
```

### Performance Optimization

1. **Batch Processing**: Use batch tools for multiple items
2. **Caching**: Leverage caching tools for repeated operations
3. **Parallel Execution**: Use parallel options where available
4. **Resource Limits**: Set appropriate limits to prevent overload
5. **Monitoring**: Use monitoring tools to track performance

### Security Considerations

1. **Authentication**: Always authenticate users before tool access
2. **Authorization**: Check permissions for each operation
3. **Audit Logging**: Record all significant operations
4. **Input Validation**: Validate all inputs before processing
5. **Rate Limiting**: Use rate limiting to prevent abuse

---

## Tool Registration and Discovery

Tools are automatically registered through the MCP server's discovery system. The registration process:

1. **Auto-Discovery**: Tools are discovered in their respective directories
2. **Registration**: Each tool is registered with its metadata
3. **Categorization**: Tools are organized by category
4. **Validation**: Tool interfaces are validated
5. **Availability**: Tools become available through the MCP interface

### Manual Tool Registration

For custom tools, use the registration system:

```python
from ipfs_datasets_py.mcp_server.tools.tool_registration import MCPToolRegistry

registry = MCPToolRegistry()
registry.register_tool(custom_tool)
```

---

## Integration with AI Assistants

These tools are designed to work seamlessly with AI assistants through the MCP protocol:

1. **Standardized Interface**: All tools follow MCP standards
2. **Rich Metadata**: Tools provide comprehensive metadata
3. **Error Handling**: Consistent error reporting
4. **Documentation**: Built-in documentation and examples
5. **Type Safety**: Parameter validation and type checking

This comprehensive reference provides complete coverage of all MCP tools available in the `ipfs_datasets_py` project, enabling effective use by AI assistants and human developers alike.
