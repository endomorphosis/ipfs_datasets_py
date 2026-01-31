# MCP Tools Technical Reference & Usage Guide

## Overview

This document provides detailed technical specifications, usage patterns, and integration examples for all MCP tools in the IPFS Datasets package. This guide is intended for developers and system integrators who need comprehensive information about tool capabilities and implementation details.

---

## Tool Architecture & Design Patterns

### Common Tool Structure

All MCP tools follow a consistent architecture:

```python
async def tool_function(
    param1: Type,
    param2: Optional[Type] = None,
    **kwargs
) -> Dict[str, Any]:
    """
    Tool description with clear purpose and usage context.
    
    Args:
        param1: Description of required parameter
        param2: Description of optional parameter
        
    Returns:
        Standardized response dictionary
    """
    try:
        # Input validation
        # Core logic
        # Return structured response
        return {
            "status": "success",
            "data": result_data,
            "metadata": operation_metadata
        }
    except Exception as e:
        return {
            "status": "error",
            "message": str(e),
            "error_type": type(e).__name__
        }
```

### Response Format Standards

All tools return consistent response formats:

```json
{
  "status": "success|error",
  "data": {}, // Tool-specific data
  "metadata": {
    "timestamp": "ISO-8601",
    "execution_time": "float",
    "tool_version": "string"
  },
  "message": "string", // Error message if status is error
  "error_type": "string" // Exception type if error
}
```

---

## Detailed Tool Specifications

### 1. Dataset Management Tools

#### `load_dataset`

**Function Signature**: 
```python
async def load_dataset(
    source: str,
    format: Optional[str] = None,
    options: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]
```

**Detailed Parameters**:
- `source`: Dataset source with multiple supported formats:
  - Hugging Face Hub: `"squad"`, `"glue/mnli"`, `"microsoft/orca-math"`
  - Local files: `"/path/to/dataset.json"`, `"./data/file.csv"`
  - URLs: `"https://example.com/data.json"`
  - IPFS: `"ipfs://QmHash..."`

- `format`: Explicit format specification:
  - `"json"`: JSON Lines or standard JSON
  - `"csv"`: Comma-separated values
  - `"parquet"`: Apache Parquet format
  - `"arrow"`: Apache Arrow format
  - `"text"`: Plain text files
  - `"xml"`: XML documents

- `options`: Advanced loading options:
  ```python
  {
    "split": "train",  # HF dataset split
    "streaming": True,  # Stream large datasets
    "cache_dir": "/path/to/cache",
    "trust_remote_code": True,
    "verification_mode": "no_checks",
    "num_proc": 4  # Parallel processing
  }
  ```

**Response Format**:
```json
{
  "status": "success",
  "dataset_id": "uuid-generated-id",
  "metadata": {
    "description": "Dataset description",
    "features": {
      "column_name": {
        "dtype": "string",
        "nullable": true
      }
    },
    "num_rows": 1000,
    "num_columns": 5,
    "dataset_size": "2.5MB"
  },
  "summary": {
    "source": "original_source",
    "format": "detected_format",
    "record_count": 1000,
    "schema": ["col1", "col2", "col3"]
  }
}
```

**Usage Examples**:

1. **Loading HuggingFace Dataset**:
```python
result = await load_dataset("squad", options={"split": "train"})
dataset_id = result["dataset_id"]
```

2. **Loading Local CSV with Options**:
```python
result = await load_dataset(
    "/data/sales.csv",
    format="csv",
    options={
        "delimiter": ";",
        "encoding": "utf-8",
        "skip_rows": 1
    }
)
```

3. **Streaming Large Dataset**:
```python
result = await load_dataset(
    "large-dataset/full",
    options={
        "streaming": True,
        "split": "train"
    }
)
```

#### `process_dataset`

**Function Signature**:
```python
async def process_dataset(
    dataset_source: Union[str, Dict[str, Any]],
    operations: List[Dict[str, Any]],
    output_id: Optional[str] = None
) -> Dict[str, Any]
```

**Operation Types & Specifications**:

1. **Filter Operations**:
```python
{
  "type": "filter",
  "column": "score",
  "condition": "greater_than",
  "value": 0.8
}
```

2. **Map/Transform Operations**:
```python
{
  "type": "map",
  "function": "lambda x: x.lower()",
  "column": "text",
  "output_column": "text_lower"
}
```

3. **Select Operations**:
```python
{
  "type": "select",
  "columns": ["id", "text", "label"]
}
```

4. **Sort Operations**:
```python
{
  "type": "sort",
  "column": "timestamp",
  "ascending": False
}
```

5. **Aggregate Operations**:
```python
{
  "type": "aggregate",
  "groupby": ["category"],
  "aggregations": {
    "count": "size",
    "avg_score": {"score": "mean"}
  }
}
```

**Complex Processing Example**:
```python
operations = [
    {
        "type": "filter",
        "column": "quality_score",
        "condition": "greater_than",
        "value": 0.7
    },
    {
        "type": "map",
        "function": "lambda x: x.strip().lower()",
        "column": "text"
    },
    {
        "type": "select",
        "columns": ["id", "text", "category", "quality_score"]
    },
    {
        "type": "sort",
        "column": "quality_score",
        "ascending": False
    }
]

result = await process_dataset(dataset_id, operations)
```

### 2. Vector & Embedding Tools

#### `create_vector_index`

**Function Signature**:
```python
async def create_vector_index(
    vectors: List[List[float]],
    dimension: Optional[int] = None,
    metric: str = "cosine",
    metadata: Optional[List[Dict[str, Any]]] = None,
    index_id: Optional[str] = None,
    index_name: Optional[str] = None
) -> Dict[str, Any]
```

**Supported Metrics**:
- `"cosine"`: Cosine similarity (recommended for normalized vectors)
- `"l2"`: Euclidean distance
- `"ip"`: Inner product
- `"manhattan"`: Manhattan distance

**Backend Support**:
The tool automatically selects the best backend based on:
- Vector count: Small (<10k), Medium (10k-100k), Large (>100k)
- Dimension: Low (<100), Medium (100-1000), High (>1000)
- Available libraries: FAISS, Qdrant, Elasticsearch

**Usage Examples**:

1. **Basic Vector Index**:
```python
vectors = [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]
result = await create_vector_index(
    vectors=vectors,
    metric="cosine",
    index_name="document_embeddings"
)
```

2. **Large-Scale Index with Metadata**:
```python
vectors = [embedding_list_1000k]  # 1M vectors
metadata = [{"doc_id": i, "source": f"doc_{i}"} for i in range(1000000)]

result = await create_vector_index(
    vectors=vectors,
    dimension=768,
    metric="cosine",
    metadata=metadata,
    index_name="large_collection"
)
```

#### `search_vector_index`

**Function Signature**:
```python
async def search_vector_index(
    index_id: str,
    query_vector: List[float],
    top_k: int = 5,
    include_metadata: bool = True,
    include_distances: bool = True,
    filter_metadata: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]
```

**Filter Metadata Examples**:
```python
# Exact match filter
filter_metadata = {"category": "science"}

# Range filter
filter_metadata = {"score": {"$gte": 0.8, "$lte": 1.0}}

# Complex filter
filter_metadata = {
    "category": {"$in": ["science", "technology"]},
    "year": {"$gte": 2020},
    "author": {"$ne": "anonymous"}
}
```

### 3. Embedding Generation Tools

#### `generate_embedding`

**Function Signature**:
```python
async def create_embeddings(
    texts: Union[str, List[str]],
    model: str = "thenlper/gte-small",
    endpoint_type: str = "local",
    endpoint_url: Optional[str] = None,
    batch_size: int = 32,
    max_length: int = 512,
    device: str = "cpu"
) -> Dict[str, Any]
```

**Supported Models**:
- **Sentence Transformers**: `"sentence-transformers/all-MiniLM-L6-v2"`
- **GTE Models**: `"thenlper/gte-small"`, `"thenlper/gte-base"`, `"thenlper/gte-large"`
- **E5 Models**: `"intfloat/e5-small-v2"`, `"intfloat/e5-base-v2"`
- **BGE Models**: `"BAAI/bge-small-en"`, `"BAAI/bge-base-en"`

**Endpoint Types**:
- `"local"`: Local model inference using transformers
- `"tei"`: Text Embeddings Inference server
- `"openvino"`: OpenVINO optimized inference
- `"libp2p"`: Distributed p2p inference

**Performance Optimization**:
```python
# GPU acceleration
result = await create_embeddings(
    texts=large_text_list,
    model="thenlper/gte-base",
    endpoint_type="local",
    device="cuda",
    batch_size=64
)

# TEI server for production
result = await create_embeddings(
    texts=texts,
    model="thenlper/gte-large",
    endpoint_type="tei",
    endpoint_url="http://tei-server:8080"
)
```

### 4. Workflow Orchestration

#### `execute_workflow`

**Function Signature**:
```python
async def execute_workflow(
    workflow_definition: Dict[str, Any],
    workflow_id: Optional[str] = None,
    context: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]
```

**Workflow Definition Structure**:
```python
workflow_definition = {
    "name": "Data Processing Pipeline",
    "description": "Load, process, and index documents",
    "version": "1.0",
    "steps": [
        {
            "id": "load_data",
            "type": "dataset_processing",
            "parameters": {
                "source": "documents.json",
                "format": "json"
            },
            "critical": True
        },
        {
            "id": "generate_embeddings",
            "type": "embedding_generation",
            "parameters": {
                "model": "thenlper/gte-base",
                "batch_size": 32
            },
            "depends_on": ["load_data"]
        },
        {
            "id": "create_index",
            "type": "vector_indexing",
            "parameters": {
                "metric": "cosine",
                "index_name": "document_index"
            },
            "depends_on": ["generate_embeddings"]
        }
    ],
    "error_handling": {
        "retry_attempts": 3,
        "retry_delay": 5,
        "continue_on_error": False
    }
}
```

**Step Types & Parameters**:

1. **Dataset Processing**:
```python
{
    "type": "dataset_processing",
    "parameters": {
        "operation": "load|process|save",
        "source": "data_source",
        "operations": [...]  # For process operation
    }
}
```

2. **Embedding Generation**:
```python
{
    "type": "embedding_generation",
    "parameters": {
        "model": "model_name",
        "endpoint_type": "local|tei|openvino",
        "batch_size": 32,
        "text_column": "text"
    }
}
```

3. **Vector Indexing**:
```python
{
    "type": "vector_indexing",
    "parameters": {
        "metric": "cosine",
        "index_name": "index_name",
        "include_metadata": True
    }
}
```

4. **Conditional Logic**:
```python
{
    "type": "conditional",
    "parameters": {
        "condition": "context.record_count > 1000",
        "true_steps": ["large_batch_processing"],
        "false_steps": ["small_batch_processing"]
    }
}
```

5. **Parallel Execution**:
```python
{
    "type": "parallel",
    "parameters": {
        "parallel_steps": [
            {"type": "embedding_generation", "parameters": {...}},
            {"type": "data_validation", "parameters": {...}}
        ],
        "max_concurrency": 3
    }
}
```

### 5. Advanced Analysis Tools

#### `cluster_analysis`

**Function Signature**:
```python
async def cluster_analysis(
    data: Union[List[List[float]], Dict[str, Any]],
    algorithm: str = "kmeans",
    n_clusters: Optional[int] = None,
    parameters: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]
```

**Supported Algorithms**:

1. **K-Means**:
```python
parameters = {
    "n_clusters": 5,
    "random_state": 42,
    "max_iter": 300,
    "n_init": 10
}
```

2. **DBSCAN**:
```python
parameters = {
    "eps": 0.5,
    "min_samples": 5,
    "metric": "euclidean"
}
```

3. **Hierarchical Clustering**:
```python
parameters = {
    "linkage": "ward",
    "distance_threshold": 0.7,
    "n_clusters": None
}
```

4. **Gaussian Mixture**:
```python
parameters = {
    "n_components": 5,
    "covariance_type": "full",
    "random_state": 42
}
```

**Usage Example**:
```python
# Cluster embeddings
result = await cluster_analysis(
    data=embedding_vectors,
    algorithm="kmeans",
    n_clusters=10,
    parameters={
        "random_state": 42,
        "n_init": 20
    }
)

cluster_labels = result["cluster_labels"]
centroids = result["centroids"]
metrics = result["metrics"]
```

#### `quality_assessment`

**Function Signature**:
```python
async def quality_assessment(
    data: Dict[str, Any],
    metrics: List[str] = ["completeness", "consistency", "accuracy"],
    thresholds: Optional[Dict[str, float]] = None
) -> Dict[str, Any]
```

**Available Metrics**:
- `"completeness"`: Percentage of non-null values
- `"consistency"`: Data format consistency
- `"accuracy"`: Data accuracy validation
- `"uniqueness"`: Duplicate detection
- `"validity"`: Schema compliance
- `"anomaly_detection"`: Outlier identification

**Threshold Configuration**:
```python
thresholds = {
    "completeness": 0.95,  # 95% non-null
    "consistency": 0.90,   # 90% format consistency
    "accuracy": 0.85,      # 85% accuracy score
    "uniqueness": 0.98     # 98% unique records
}
```

### 6. System Management Tools

#### `health_check`

**Function Signature**:
```python
async def health_check(
    components: Optional[List[str]] = None,
    include_details: bool = True,
    timeout: int = 30
) -> Dict[str, Any]
```

**Component Categories**:
- `"system"`: CPU, memory, disk usage
- `"services"`: Service status and connectivity
- `"embeddings"`: Embedding model availability
- `"vector_stores"`: Vector database health
- `"ipfs"`: IPFS node status
- `"cache"`: Cache system health

**Response Format**:
```json
{
  "status": "healthy|degraded|unhealthy",
  "overall_score": 0.95,
  "components": {
    "system": {
      "status": "healthy",
      "cpu_usage": 45.2,
      "memory_usage": 67.8,
      "disk_usage": 23.4
    },
    "services": {
      "status": "healthy",
      "active_services": 12,
      "failed_services": 0
    }
  },
  "recommendations": [
    "Consider scaling up if CPU usage exceeds 80%"
  ]
}
```

---

## Integration Patterns & Best Practices

### 1. Data Processing Pipeline

**Pattern**: `Load → Process → Embed → Index → Store`

```python
async def complete_data_pipeline(source: str):
    # Step 1: Load dataset
    load_result = await load_dataset(source)
    dataset_id = load_result["dataset_id"]
    
    # Step 2: Process and clean
    process_result = await process_dataset(
        dataset_id,
        operations=[
            {"type": "filter", "column": "quality", "condition": "greater_than", "value": 0.7},
            {"type": "select", "columns": ["id", "text", "metadata"]}
        ]
    )
    processed_id = process_result["dataset_id"]
    
    # Step 3: Generate embeddings
    embed_result = await create_embeddings(
        texts=get_texts_from_dataset(processed_id),
        model="thenlper/gte-base"
    )
    embeddings = embed_result["embeddings"]
    
    # Step 4: Create vector index
    index_result = await create_vector_index(
        vectors=embeddings,
        metric="cosine",
        metadata=get_metadata_from_dataset(processed_id)
    )
    
    # Step 5: Store to IPFS
    ipfs_result = await pin_to_ipfs(processed_id)
    
    return {
        "dataset_id": processed_id,
        "index_id": index_result["index_id"],
        "ipfs_cid": ipfs_result["cid"]
    }
```

### 2. Semantic Search System

**Pattern**: `Query → Embed → Search → Rank → Return`

```python
async def semantic_search_system(query: str, index_id: str):
    # Step 1: Generate query embedding
    query_result = await create_embeddings(
        texts=[query],
        model="thenlper/gte-base"
    )
    query_vector = query_result["embeddings"][0]
    
    # Step 2: Search vector index
    search_result = await search_vector_index(
        index_id=index_id,
        query_vector=query_vector,
        top_k=20,
        include_metadata=True
    )
    
    # Step 3: Apply additional filtering/ranking
    filtered_results = await apply_business_logic_filters(
        search_result["results"]
    )
    
    return filtered_results
```

### 3. Batch Processing Workflow

**Pattern**: `Schedule → Monitor → Process → Aggregate → Report`

```python
workflow_definition = {
    "name": "Daily Batch Processing",
    "steps": [
        {
            "id": "load_daily_data",
            "type": "dataset_processing",
            "parameters": {
                "source": "daily_uploads/*.json",
                "format": "json"
            }
        },
        {
            "id": "quality_check",
            "type": "quality_assessment",
            "parameters": {
                "metrics": ["completeness", "validity"],
                "thresholds": {"completeness": 0.95}
            }
        },
        {
            "id": "process_if_quality_ok",
            "type": "conditional",
            "parameters": {
                "condition": "context.quality_score > 0.9",
                "true_steps": ["embedding_generation", "indexing"],
                "false_steps": ["quality_report", "alert"]
            }
        }
    ]
}

result = await execute_workflow(workflow_definition)
```

### 4. Real-time Monitoring

**Pattern**: `Monitor → Alert → Diagnose → Report`

```python
async def monitoring_system():
    # Comprehensive health check
    health = await health_check(
        components=["system", "services", "embeddings"],
        include_details=True
    )
    
    # Performance metrics
    metrics = await get_performance_metrics(
        time_range="1h",
        include_trends=True
    )
    
    # Generate alerts if needed
    if health["overall_score"] < 0.8:
        alert_result = await generate_alert(
            severity="warning",
            components=health["degraded_components"]
        )
    
    # Create monitoring report
    report = await generate_monitoring_report(
        health_data=health,
        metrics_data=metrics,
        format="json"
    )
    
    return report
```

---

## Performance Optimization Guidelines

### 1. Vector Operations
- Use batch operations for multiple vectors
- Choose appropriate metric for your use case
- Consider dimensionality reduction for high-dimensional data
- Use memory-efficient backends for large datasets

### 2. Embedding Generation
- Use GPU acceleration when available
- Optimize batch sizes based on available memory
- Cache embeddings for repeated use
- Use TEI servers for production deployments

### 3. Dataset Processing
- Stream large datasets to avoid memory issues
- Use parallel processing for CPU-intensive operations
- Apply filters early to reduce data volume
- Cache intermediate results

### 4. Workflow Optimization
- Use parallel steps where possible
- Implement proper error handling and retry logic
- Monitor resource usage during execution
- Use conditional logic to optimize paths

---

## Error Handling & Troubleshooting

### Common Error Patterns

1. **Resource Exhaustion**:
```python
{
  "status": "error",
  "error_type": "ResourceError",
  "message": "Insufficient memory for operation",
  "suggestions": [
    "Reduce batch size",
    "Use streaming mode",
    "Add more memory"
  ]
}
```

2. **Invalid Parameters**:
```python
{
  "status": "error",
  "error_type": "ValidationError",
  "message": "Invalid vector dimension",
  "parameter": "vectors",
  "expected": "List of equal-length vectors",
  "received": "Mixed dimensions"
}
```

3. **Service Unavailable**:
```python
{
  "status": "error",
  "error_type": "ServiceError",
  "message": "Embedding service unreachable",
  "service": "tei-server",
  "retry_in": 30
}
```

### Debugging Tools

Use the monitoring and diagnostic tools:
```python
# Check system health
health = await health_check(include_details=True)

# Get performance metrics
metrics = await get_performance_metrics()

# Generate diagnostic report
report = await generate_monitoring_report()
```

This technical reference provides comprehensive information for effectively implementing and integrating the MCP tools in production environments.
