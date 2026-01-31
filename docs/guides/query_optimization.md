# Query Optimization Guide

This guide covers techniques for optimizing queries in IPFS Datasets Python, including vector search, graph queries, and hybrid approaches.

## Table of Contents

1. [Introduction](#introduction)
2. [Vector Query Optimization](#vector-query-optimization)
3. [Graph Query Optimization](#graph-query-optimization)
4. [GraphRAG Query Optimization](#graphrag-query-optimization)
5. [Distributed Query Optimization](#distributed-query-optimization)
6. [Query Planning](#query-planning)
7. [Result Caching](#result-caching)
8. [Performance Monitoring](#performance-monitoring)
9. [Tuning Parameters](#tuning-parameters)
10. [Metrics and Visualization](#metrics-and-visualization)
11. [Best Practices](#best-practices)

## Introduction

Query optimization is critical for achieving good performance, especially when working with large datasets and complex query patterns. IPFS Datasets Python offers several optimization techniques for different types of queries.

## Vector Query Optimization

Optimize vector similarity search queries for better performance.

### Index Type Selection

Choose the appropriate index type based on your requirements:

```python
from ipfs_datasets_py.ipfs_knn_index import IPFSKnnIndex

# Flat index (exact search, slower but more accurate)
flat_index = IPFSKnnIndex(
    dimension=768,
    metric="cosine",
    index_type="flat"
)

# HNSW index (approximate search, much faster for large datasets)
hnsw_index = IPFSKnnIndex(
    dimension=768,
    metric="cosine",
    index_type="hnsw",
    hnsw_params={
        "M": 16,  # Number of connections per layer
        "ef_construction": 200,  # Size of dynamic candidate list during construction
        "ef_search": 100  # Size of dynamic candidate list during search
    }
)
```

### Search Parameter Optimization

```python
# Balance between speed and accuracy
results = index.search(
    query_vector=query_vector,
    top_k=10,
    optimization_level=2,  # 1-3, higher is faster but potentially less accurate
    nprobe=20  # Number of clusters to search (for IVF indices)
)

# Optimized for speed
fast_results = index.search(
    query_vector=query_vector,
    top_k=10,
    optimization_level=3,
    early_stopping=True
)

# Optimized for accuracy
accurate_results = index.search(
    query_vector=query_vector,
    top_k=10,
    optimization_level=1,
    early_stopping=False
)
```

### Multi-Model Vector Search

Use multiple embedding models for better results:

```python
from ipfs_datasets_py.ipfs_knn_index import MultiModelSearch

# Create multi-model searcher
searcher = MultiModelSearch(
    models={
        "miniLM": {"dimension": 384, "weight": 0.3},
        "mpnet": {"dimension": 768, "weight": 0.7}
    }
)

# Add vectors for each model
searcher.add_vectors(
    model_name="miniLM",
    vectors=vectors_miniLM,
    metadata=metadata
)
searcher.add_vectors(
    model_name="mpnet",
    vectors=vectors_mpnet,
    metadata=metadata
)

# Perform multi-model search
results = searcher.search(
    query_vectors={
        "miniLM": query_vector_miniLM,
        "mpnet": query_vector_mpnet
    },
    top_k=10,
    aggregation_method="weighted"  # "weighted", "rank_fusion", or "intersection"
)
```

## Graph Query Optimization

Optimize graph-based queries for better performance.

### Path Optimization

```python
from ipfs_datasets_py.knowledge_graph import KnowledgeGraphQuery

# Create query optimizer
query = KnowledgeGraphQuery(
    knowledge_graph=kg,
    optimize_paths=True
)

# Query with path optimization
results = query.execute(
    start_node="entity123",
    relationships=[
        {"type": "HAS_ATTRIBUTE", "direction": "outgoing"},
        {"type": "RELATED_TO", "direction": "any"}
    ],
    max_depth=3,
    optimization_strategy="shortest_path"
)
```

### Query Pattern Recognition

```python
from ipfs_datasets_py.knowledge_graph import PatternOptimizer

# Create pattern optimizer
optimizer = PatternOptimizer(knowledge_graph=kg)

# Optimize query based on recognized patterns
optimized_query = optimizer.optimize(
    query={
        "start_node": "entity123",
        "pattern": [
            {"type": "HAS_ATTRIBUTE", "direction": "outgoing"},
            {"type": "RELATED_TO", "direction": "any"}
        ]
    }
)

# Execute optimized query
results = kg.execute_query(optimized_query)
```

### Index-Based Optimization

```python
from ipfs_datasets_py.knowledge_graph import IndexedKnowledgeGraph

# Create indexed knowledge graph
indexed_kg = IndexedKnowledgeGraph(
    index_types=["entity_type", "relationship_type", "property_value"],
    auto_index_threshold=1000  # Auto-index relationships with > 1000 instances
)

# Add entities and relationships to build indexes automatically
indexed_kg.add_entity(...)
indexed_kg.add_relationship(...)

# Query using indexes
results = indexed_kg.query(
    entity_type="Person",
    properties={"country": "Germany"},
    use_indexes=True
)
```

## GraphRAG Query Optimization

Optimize hybrid queries that combine vector similarity and graph traversal.

### GraphRAG Query Optimizer

```python
from ipfs_datasets_py.rag.rag_query_optimizer import UnifiedGraphRAGQueryOptimizer, QueryRewriter, QueryBudgetManager

# Create specialized components
query_rewriter = QueryRewriter()
budget_manager = QueryBudgetManager()

# Create unified GraphRAG query optimizer with graph type information
optimizer = UnifiedGraphRAGQueryOptimizer(
    rewriter=query_rewriter,
    budget_manager=budget_manager,
    graph_info={
        "graph_type": "wikipedia",
        "edge_selectivity": {
            "instance_of": 0.1,
            "subclass_of": 0.05,
            "part_of": 0.2,
            "located_in": 0.15,
            "created_by": 0.3
        },
        "graph_density": 0.4
    }
)

# Create a sample query with a query vector
query = {
    "query_vector": query_vector,
    "max_vector_results": 10,
    "max_traversal_depth": 3,
    "edge_types": ["instance_of", "part_of", "created_by"],
    "min_similarity": 0.6,
    "query_text": "What is the relationship between quantum mechanics and general relativity?"
}

# Get optimized query plan
plan = optimizer.optimize_query(query, priority="high")

# Execute the query with a GraphRAG processor
results, execution_info = optimizer.execute_query(processor, query, priority="high")
```

### IPLD-Specific GraphRAG Optimization

For content-addressed graphs using IPLD (InterPlanetary Linked Data), specialized optimizations are applied:

```python
from ipfs_datasets_py.rag.rag_query_optimizer import UnifiedGraphRAGQueryOptimizer

# Create optimizer with IPLD-specific graph info
ipld_optimizer = UnifiedGraphRAGQueryOptimizer(
    graph_info={
        "graph_type": "ipld",
        "edge_selectivity": {
            "links_to": 0.3,
            "links_from": 0.4,
            "contains": 0.2,
            "references": 0.5
        },
        "graph_density": 0.4
    }
)

# Create a query for content-addressed data
ipld_query = {
    "query_vector": query_vector,
    "max_vector_results": 5,
    "max_traversal_depth": 3,
    "graph_type": "ipld",  # Explicitly specify IPLD graph type
    "query_text": "How does IPFS implement CID-based content addressing?"
}

# Get optimized plan with IPLD-specific optimizations
plan = ipld_optimizer.optimize_query(ipld_query)

# Execute with a processor that supports IPLD DAG traversal
results, info = ipld_optimizer.execute_query(ipld_processor, ipld_query)

# The IPLD-specific optimizations include:
# - DAG traversal strategy optimized for content-addressed data
# - CID path optimization for efficient traversal
# - Block batch loading for improved performance
# - Path caching for repeated traversals
# - Vector dimensionality reduction for faster similarity search
```

### Performance Analysis and Recommendations

```python
from ipfs_datasets_py.rag.rag_query_optimizer import UnifiedGraphRAGQueryOptimizer

# Analyze query performance
performance_analysis = optimizer.analyze_performance(recent_window_seconds=300.0)

# Get recommendations for improving query performance
for recommendation in performance_analysis["recommendations"]:
    print(f"Recommendation: {recommendation['description']}")
    
# Example recommendations:
# - "Low cache hit rate. Consider increasing cache size or TTL."
# - "High average query time. Consider reducing traversal depth or vector results."
# - "Common query pattern with high traversal depth (4). Consider reducing depth."
```

### Query Budget Management

```python
from ipfs_datasets_py.rag.rag_query_optimizer import QueryBudgetManager

# Create budget manager with custom budgets
budget_manager = QueryBudgetManager(
    default_budget={
        "vector_search_ms": 500.0,    # Vector search budget in milliseconds
        "graph_traversal_ms": 1000.0, # Graph traversal budget in milliseconds
        "ranking_ms": 200.0,          # Ranking budget in milliseconds
        "max_nodes": 1000,            # Maximum nodes to visit
        "max_edges": 5000,            # Maximum edges to traverse
        "timeout_ms": 2000.0          # Total query timeout in milliseconds
    }
)

# Allocate budget for a query based on priority
budget = budget_manager.allocate_budget(
    query=query, 
    priority="critical"  # "low", "normal", "high", or "critical"
)

# Track resource consumption during execution
budget_manager.track_consumption("vector_search_ms", 250.0)
budget_manager.track_consumption("graph_traversal_ms", 800.0)
budget_manager.track_consumption("nodes_visited", 500)

# Check if budget is exceeded
if budget_manager.is_budget_exceeded("graph_traversal_ms"):
    print("Graph traversal budget exceeded, consider early stopping")

# Get consumption report
consumption_report = budget_manager.get_current_consumption_report()
print(f"Overall consumption ratio: {consumption_report['overall_consumption_ratio']}")

# Enable early stopping based on result quality and budget consumption
if budget_manager.suggest_early_stopping(current_results, consumption_report["overall_consumption_ratio"]):
    print("Suggesting early stopping based on result quality and budget consumption")
```

### Query Rewriting

```python
from ipfs_datasets_py.rag.rag_query_optimizer import QueryRewriter

# Create query rewriter
query_rewriter = QueryRewriter()

# Rewrite a query for better performance
original_query = {
    "entity_types": ["Person", "Organization"],
    "min_similarity": 0.4,
    "traversal": {
        "max_depth": 4,
        "edge_types": ["knows", "works_for", "founded"]
    }
}

# Get graph-specific information
graph_info = {
    "graph_type": "wikipedia",
    "edge_selectivity": {
        "knows": 0.8,     # Low selectivity (many connections)
        "works_for": 0.2, # Medium selectivity
        "founded": 0.05   # High selectivity (few connections)
    },
    "graph_density": 0.6
}

# Rewrite query with graph-specific optimizations
rewritten_query = query_rewriter.rewrite_query(original_query, graph_info)

# Analyze the query to get insights and recommendations
analysis = query_rewriter.analyze_query(original_query)
print(f"Query pattern: {analysis['pattern']}")
print(f"Query complexity: {analysis['complexity']}")

for optimization in analysis["optimizations"]:
    print(f"Suggested optimization: {optimization['description']}")
```

### Specialized Optimizers for Different Graph Types

```python
from ipfs_datasets_py.rag.rag_query_optimizer import UnifiedGraphRAGQueryOptimizer

# Create a unified optimizer that detects graph type from query
unified_optimizer = UnifiedGraphRAGQueryOptimizer()

# Query with Wikipedia-specific signals
wiki_query = {
    "query_vector": query_vector,
    "query_text": "What is the relationship between quantum physics and Wikipedia articles?",
    "max_traversal_depth": 2
}

# Query with IPLD-specific signals
ipld_query = {
    "query_vector": query_vector,
    "query_text": "How does IPFS use content-addressed data with CIDs?",
    "max_traversal_depth": 2,
    "graph_type": "ipld"  # Explicitly specify graph type (optional)
}

# Get optimized query plans with graph-type-specific optimizations
wiki_plan = unified_optimizer.optimize_query(wiki_query)  # Will detect Wikipedia
ipld_plan = unified_optimizer.optimize_query(ipld_query)  # Will detect IPLD

print(f"Detected graph type for wiki query: {wiki_plan['graph_type']}")
print(f"Detected graph type for ipld query: {ipld_plan['graph_type']}")

# Different weights for different graph types
print(f"Vector weight for wiki query: {wiki_plan['weights'].get('vector', 0.7)}")
print(f"Vector weight for ipld query: {ipld_plan['weights'].get('vector', 0.7)}")

# Examine IPLD-specific optimizations in the plan
ipld_traversal = ipld_plan["query"].get("traversal", {})
print(f"IPLD using DAG traversal: {ipld_traversal.get('strategy') == 'dag_traversal'}")
print(f"IPLD using CID path optimization: {ipld_traversal.get('use_cid_path_optimization', False)}")
print(f"IPLD using batch loading: {ipld_traversal.get('batch_loading', False)}")
```

### Query Type Detection

```python
from ipfs_datasets_py.rag.rag_query_optimizer import QueryTypeDetector

# Create query type detector
detector = QueryTypeDetector()

# Detect query type
query_type = detector.detect_type(
    query_text="What is the relationship between neural networks and deep learning?",
    query_vector=query_vector
)

print(f"Query type: {query_type}")  # e.g., "relational", "factoid", "comparative"

# Optimize query based on type
if query_type == "relational":
    # Use relationship-focused optimization
    optimizer.optimize_relational_query(query_text, query_vector)
elif query_type == "factoid":
    # Use entity-focused optimization
    optimizer.optimize_factoid_query(query_text, query_vector)
elif query_type == "comparative":
    # Use comparison-focused optimization
    optimizer.optimize_comparative_query(query_text, query_vector)
```

### Hybrid Weighting

```python
from ipfs_datasets_py.rag.rag_query_optimizer import HybridWeightingOptimizer

# Create hybrid weighting optimizer
optimizer = HybridWeightingOptimizer()

# Get optimal weights for vector vs. graph components
optimal_weights = optimizer.get_optimal_weights(
    query_text="How does content addressing work in IPFS?",
    query_vector=query_vector,
    query_features={
        "entity_count": 2,
        "relationship_keywords": 1,
        "specificity": 0.7
    }
)

print(f"Vector weight: {optimal_weights['vector']}")  # e.g., 0.65
print(f"Graph weight: {optimal_weights['graph']}")    # e.g., 0.35

# Execute with optimized weights
results = graphrag_engine.query(
    query_text=query_text,
    query_vector=query_vector,
    weights=optimal_weights
)
```

## Distributed Query Optimization

Optimize queries across distributed nodes.

### Federated Query Optimization

```python
from ipfs_datasets_py.federated_search import FederatedQueryOptimizer

# Create federated query optimizer
optimizer = FederatedQueryOptimizer(
    coordinator_node=coordinator,
    worker_nodes=worker_nodes
)

# Optimize a distributed query
optimized_plan = optimizer.optimize_query(
    query={
        "type": "vector_search",
        "query_vector": query_vector,
        "top_k": 10
    },
    dataset_id="distributed-dataset-123"
)

# Get execution statistics
stats = optimizer.get_execution_stats(optimized_plan)
print(f"Estimated execution time: {stats['estimated_time']} ms")
print(f"Estimated network traffic: {stats['estimated_network_traffic']} KB")
```

### Dynamic Node Selection

```python
from ipfs_datasets_py.federated_search import DynamicNodeSelector

# Create dynamic node selector
selector = DynamicNodeSelector(
    metric_collector=metric_collector,
    selection_strategy="performance"  # "performance", "load_balanced", or "network_proximity"
)

# Select optimal nodes for a query
selected_nodes = selector.select_nodes(
    query=query,
    dataset_id=dataset_id,
    min_nodes=3,
    max_nodes=5
)

# Execute query on selected nodes
results = federated_engine.execute_on_nodes(
    query=query,
    nodes=selected_nodes
)
```

### Parallel Query Execution

```python
from ipfs_datasets_py.federated_search import ParallelQueryExecutor

# Create parallel query executor
executor = ParallelQueryExecutor(
    max_concurrent_queries=10,
    timeout_seconds=30
)

# Execute query parts in parallel
results = await executor.execute(
    query_parts=[
        {"node": "node1", "query": query1},
        {"node": "node2", "query": query2},
        {"node": "node3", "query": query3}
    ],
    merge_strategy="score_based"  # "score_based", "round_robin", or "weighted"
)
```

## Query Planning

Develop optimized query plans for complex queries.

### Query Plan Generation

```python
from ipfs_datasets_py.query_optimizer import QueryPlanner

# Create query planner
planner = QueryPlanner(
    vector_store=vector_store,
    knowledge_graph=knowledge_graph,
    distributed_nodes=nodes
)

# Generate query plan
plan = planner.generate_plan(
    query_text="How does IPFS implement content addressing?",
    query_vector=query_vector,
    optimization_goal="balanced"  # "speed", "accuracy", or "balanced"
)

# Inspect plan steps
for i, step in enumerate(plan.steps):
    print(f"Step {i+1}: {step['operation']} - {step['description']}")

# Execute plan
results = planner.execute_plan(plan)
```

### Cost-Based Optimization

```python
from ipfs_datasets_py.query_optimizer import CostBasedOptimizer

# Create cost-based optimizer
optimizer = CostBasedOptimizer(
    cost_model={
        "vector_search": {"base_cost": 10, "per_item_cost": 0.01},
        "graph_traversal": {"base_cost": 5, "per_hop_cost": 3},
        "node_communication": {"base_cost": 20, "per_kb_cost": 0.1}
    }
)

# Generate alternative plans
alternative_plans = optimizer.generate_alternatives(query)

# Estimate cost for each plan
for plan in alternative_plans:
    cost = optimizer.estimate_cost(plan)
    print(f"Plan {plan.id}: Estimated cost {cost}")

# Select optimal plan
optimal_plan = optimizer.select_optimal_plan(alternative_plans)
```

### Query Rewriting

```python
from ipfs_datasets_py.rag.rag_query_optimizer import QueryRewriter

# Create query rewriter with specific optimization capabilities
rewriter = QueryRewriter(
    enable_predicate_pushdown=True,
    enable_join_reordering=True,
    enable_traversal_optimization=True,
    enable_pattern_optimization=True,
    pattern_library={
        "entity_centric": {
            "description": "Query focused on a specific entity and its relationships",
            "indicators": ["about", "information on"],
            "optimization": {"max_traversal_depth": 1}
        },
        "comparison": {
            "description": "Query comparing multiple entities or concepts",
            "indicators": ["compare", "difference between", "versus"],
            "optimization": {"max_traversal_depth": 2, "max_branch_factor": 3}
        }
    }
)

# Rewrite GraphRAG query for better performance
rewritten_query = rewriter.rewrite_query(
    query_spec={
        "query_text": "What is the relationship between IPFS and Filecoin?",
        "params": {
            "max_vector_results": 5,
            "max_traversal_depth": 3,
            "min_similarity": 0.7
        }
    },
    graph_metadata={
        "graph_type": "ipld",
        "entity_types": ["Technology", "Protocol"]
    }
)

# Get statistics about rewrites
stats = rewriter.get_rewrite_stats()
print(f"Total rewrites: {stats['total_rewrites']}")
print(f"Pattern matches: {stats['pattern_matches']}")
print(f"Predicate pushdowns: {stats['predicate_pushdowns']}")
print(f"Optimization rate: {stats['rewrite_rate']:.2f}")
```

For SQL-like queries, you can use the general query rewriter:

```python
from ipfs_datasets_py.query_optimizer import SQLQueryRewriter

# Create SQL query rewriter
sql_rewriter = SQLQueryRewriter()

# Rewrite SQL query for better performance
rewritten_sql = sql_rewriter.rewrite(
    query="SELECT * FROM dataset WHERE column1 = 'value' AND column2 > 100",
    statistics=table_statistics,
    indexes=available_indexes
)

print(f"Original query: {query}")
print(f"Rewritten query: {rewritten_sql}")
```

## Result Caching

Implement caching for faster repeated queries.

### Query Result Cache

```python
from ipfs_datasets_py.query_optimizer import QueryResultCache

# Create query result cache
cache = QueryResultCache(
    max_size=1000,  # Maximum number of cached results
    ttl_seconds=3600,  # Cache entries expire after 1 hour
    eviction_policy="lru"  # Least Recently Used
)

# Generate cache key
cache_key = cache.generate_key(query, parameters)

# Try to get cached result
cached_result = cache.get(cache_key)
if cached_result is not None:
    # Use cached result
    return cached_result
else:
    # Execute query and cache result
    result = execute_query(query, parameters)
    cache.put(cache_key, result)
    return result
```

### Semantic Cache

```python
from ipfs_datasets_py.query_optimizer import SemanticCache

# Create semantic cache
semantic_cache = SemanticCache(
    vector_dimension=768,
    similarity_threshold=0.95,  # Threshold for considering queries similar
    max_size=500
)

# Query with semantic caching
result = semantic_cache.query(
    query_text="How does IPFS implement content addressing?",
    query_vector=query_vector,
    query_function=lambda q, v: execute_query(q, v)
)
```

### Partial Result Caching

```python
from ipfs_datasets_py.query_optimizer import PartialResultCache

# Create partial result cache
partial_cache = PartialResultCache()

# Try to get partial results
partial_results = partial_cache.get_partial_results(query, parameters)
if partial_results:
    # Execute only the remaining parts of the query
    remaining_results = execute_partial_query(query, parameters, partial_results)
    
    # Combine partial and remaining results
    final_results = partial_cache.combine_results(partial_results, remaining_results)
else:
    # Execute full query
    final_results = execute_query(query, parameters)
    
    # Cache individual components for future partial matches
    partial_cache.cache_components(query, parameters, final_results)
```

## Performance Monitoring

Monitor query performance for optimization.

### Query Profiling

```python
from ipfs_datasets_py.query_optimizer import QueryProfiler

# Create query profiler
profiler = QueryProfiler()

# Profile query execution
with profiler.profile(query, parameters) as profile:
    # Execute query
    result = execute_query(query, parameters)

# Get detailed performance metrics
metrics = profile.get_metrics()
print(f"Execution time: {metrics['execution_time']} ms")
print(f"Memory usage: {metrics['memory_usage']} MB")
print(f"CPU usage: {metrics['cpu_usage']}%")

# Identify bottlenecks
bottlenecks = profile.identify_bottlenecks()
for bottleneck in bottlenecks:
    print(f"Bottleneck: {bottleneck['component']}, Impact: {bottleneck['impact']}")

# Get optimization recommendations
recommendations = profile.get_recommendations()
for recommendation in recommendations:
    print(f"Recommendation: {recommendation['description']}")
```

### Performance Metrics Collection

```python
from ipfs_datasets_py.query_optimizer import PerformanceMetricsCollector

# Create metrics collector
metrics_collector = PerformanceMetricsCollector(
    metrics_to_collect=["execution_time", "memory_usage", "result_count"]
)

# Record metrics for a query
metrics_collector.record(
    query_id="query123",
    query_text="How does IPFS implement content addressing?",
    query_type="graphrag",
    metrics={
        "execution_time": 150,  # ms
        "memory_usage": 25,     # MB
        "result_count": 10
    }
)

# Get average metrics by query type
avg_metrics = metrics_collector.get_average_metrics_by_type()
print(f"Avg execution time for GraphRAG queries: {avg_metrics['graphrag']['execution_time']} ms")

# Get performance trends
trends = metrics_collector.get_trends(
    query_type="graphrag",
    metric="execution_time",
    window=24  # hours
)
```

### Query Store

```python
from ipfs_datasets_py.query_optimizer import QueryStore

# Create query store
query_store = QueryStore(storage_path="query_store.db")

# Store query with its plan and performance metrics
query_store.store(
    query_id="query123",
    query_text="How does IPFS implement content addressing?",
    query_plan=plan,
    performance_metrics={
        "execution_time": 150,
        "memory_usage": 25
    }
)

# Find similar queries
similar_queries = query_store.find_similar(
    query_text="How does content addressing work in IPFS?",
    limit=5
)

# Get performance comparison
comparison = query_store.compare_performance(
    query_ids=["query123", "query456"],
    metrics=["execution_time", "memory_usage"]
)
```

## Tuning Parameters

Tune query optimization parameters for better performance.

### Auto-Tuning

```python
from ipfs_datasets_py.query_optimizer import AutoTuner

# Create auto-tuner
tuner = AutoTuner(
    parameters_to_tune=["vector_weight", "max_hops", "ef_search"],
    optimization_goal="balanced"  # "speed", "accuracy", or "balanced"
)

# Start tuning process
tuning_results = tuner.tune(
    query_function=lambda params: execute_query_with_params(query, params),
    iterations=10,
    evaluate_function=lambda result: evaluate_quality(result)
)

# Get optimized parameters
optimized_params = tuner.get_optimized_parameters()
print(f"Optimized parameters: {optimized_params}")

# Apply optimized parameters
results = execute_query_with_params(query, optimized_params)
```

### Parameter Sensitivity Analysis

```python
from ipfs_datasets_py.query_optimizer import SensitivityAnalyzer

# Create sensitivity analyzer
analyzer = SensitivityAnalyzer(
    parameters=["vector_weight", "max_hops", "ef_search"],
    ranges={
        "vector_weight": [0.1, 0.9, 0.1],  # Start, stop, step
        "max_hops": [1, 5, 1],
        "ef_search": [50, 200, 50]
    }
)

# Analyze parameter sensitivity
sensitivity = analyzer.analyze(
    query_function=lambda params: execute_query_with_params(query, params),
    evaluate_function=lambda result: evaluate_quality(result)
)

# Get most sensitive parameters
most_sensitive = analyzer.get_most_sensitive_parameters(limit=2)
print(f"Most sensitive parameters: {most_sensitive}")
```

### Configuration Templates

```python
from ipfs_datasets_py.query_optimizer import ConfigurationTemplates

# Create configuration templates
templates = ConfigurationTemplates()

# Get template for a specific query type
config = templates.get_template(
    query_type="relational",
    optimization_goal="speed",
    dataset_size="large"
)

# Apply template
results = execute_query_with_config(query, config)
```

## Metrics and Visualization

IPFS Datasets Python provides comprehensive metrics collection and visualization capabilities for query optimization, allowing you to analyze query performance in detail and identify optimization opportunities.

## Query Metrics Collection

The `QueryMetricsCollector` class provides detailed metrics collection for GraphRAG queries:

```python
from ipfs_datasets_py.rag.rag_query_optimizer import QueryMetricsCollector

# Initialize metrics collector
metrics_collector = QueryMetricsCollector(
    metrics_dir="query_metrics",  # Directory to store metrics files
    track_resources=True,  # Track memory and CPU usage
    max_history_size=1000  # Maximum number of query metrics to retain
)

# Start tracking a query
query_id = metrics_collector.start_query_tracking(
    query_params={
        "max_vector_results": 5,
        "max_traversal_depth": 2,
        "edge_types": ["knows", "works_for"]
    }
)

# Time specific phases of query execution
with metrics_collector.time_phase("vector_search", {"type": "search"}):
    # Vector search code here
    time.sleep(0.2)  # Simulating work
    
# Time nested phases for detailed analysis
with metrics_collector.time_phase("graph_traversal"):
    # Graph traversal setup
    time.sleep(0.1)
    
    # Track nested operations with proper hierarchical timing
    with metrics_collector.time_phase("node_expansion"):
        # Node expansion code
        time.sleep(0.2)
        
    with metrics_collector.time_phase("path_filtering"):
        # Path filtering code
        time.sleep(0.1)

# Record custom metrics
metrics_collector.record_additional_metric(
    name="cache_hit_rate", 
    value=0.75, 
    category="cache"
)

# End tracking and get metrics
metrics = metrics_collector.end_query_tracking(
    results_count=10,
    quality_score=0.85  # Score indicating quality of results (0.0-1.0)
)

# Generate performance report
report = metrics_collector.generate_performance_report(query_id)
print(f"Total duration: {report['timing_summary']['avg_duration']:.3f}s")
print(f"Peak memory: {report['resource_usage']['max_peak_memory'] / (1024*1024):.2f} MB")

# Export metrics to CSV for external analysis
csv_data = metrics_collector.export_metrics_csv("query_metrics.csv")
```

## Query Visualization

The `QueryVisualizer` class provides various visualization capabilities for analyzing query performance:

```python
from ipfs_datasets_py.rag.rag_query_optimizer import QueryVisualizer

# Create visualizer with metrics collector
visualizer = QueryVisualizer(metrics_collector)

# Visualize phase timing breakdown
visualizer.visualize_phase_timing(
    query_id=query_id,
    title="Query Phase Timing",
    output_file="visualizations/phase_timing.png"
)

# Visualize query execution plan as a directed graph
visualizer.visualize_query_plan(
    query_plan={
        "phases": {
            "vector_search": {
                "name": "Vector Search",
                "type": "vector_search",
                "duration": 0.2,
                "dependencies": []
            },
            "graph_traversal": {
                "name": "Graph Traversal",
                "type": "graph_traversal",
                "duration": 0.4,
                "dependencies": ["vector_search"]
            },
            "node_expansion": {
                "name": "Node Expansion",
                "type": "processing",
                "duration": 0.2,
                "dependencies": ["graph_traversal"]
            },
            "path_filtering": {
                "name": "Path Filtering",
                "type": "processing",
                "duration": 0.1,
                "dependencies": ["node_expansion"]
            },
            "ranking": {
                "name": "Result Ranking",
                "type": "ranking",
                "duration": 0.1,
                "dependencies": ["path_filtering"]
            }
        }
    },
    title="Query Execution Plan",
    output_file="visualizations/query_plan.png"
)

# Visualize resource usage (memory and CPU) during query execution
visualizer.visualize_resource_usage(
    query_id=query_id,
    title="Query Resource Usage",
    output_file="visualizations/resource_usage.png"
)

# Compare performance across multiple queries
visualizer.visualize_performance_comparison(
    query_ids=["query_id1", "query_id2", "query_id3"],
    labels=["Original", "Optimized", "Fine-tuned"],
    output_file="visualizations/performance_comparison.png"
)

# Visualize common query patterns
visualizer.visualize_query_patterns(
    limit=5,
    output_file="visualizations/query_patterns.png"
)

# Generate comprehensive HTML dashboard
visualizer.export_dashboard_html(
    output_file="visualizations/query_dashboard.html",
    query_id=query_id,
    include_all_metrics=True
)
```

## Integration with Query Optimizer

The metrics collection and visualization capabilities can be integrated directly with the `UnifiedGraphRAGQueryOptimizer`:

```python
from ipfs_datasets_py.rag.rag_query_optimizer import (
    UnifiedGraphRAGQueryOptimizer,
    QueryMetricsCollector,
    QueryVisualizer
)

# Create metrics collector and visualizer
metrics_collector = QueryMetricsCollector(metrics_dir="metrics")
visualizer = QueryVisualizer(metrics_collector)

# Initialize query optimizer with metrics and visualization
optimizer = UnifiedGraphRAGQueryOptimizer(
    rewriter=query_rewriter,
    budget_manager=budget_manager,
    metrics_collector=metrics_collector,
    visualizer=visualizer
)

# Execute queries - metrics will be collected automatically
results, execution_info = optimizer.execute_query(
    processor=graph_processor,
    query={
        "query_vector": query_vector,
        "max_vector_results": 5,
        "max_traversal_depth": 2
    }
)

# The query ID is stored for convenience
query_id = optimizer.last_query_id

# Visualize query plan
optimizer.visualize_query_plan(
    query_id=query_id,
    output_file="visualizations/latest_query_plan.png"
)

# Visualize resource usage
optimizer.visualize_resource_usage(
    query_id=query_id,
    output_file="visualizations/latest_resource_usage.png"
)

# Generate dashboard with comprehensive metrics
optimizer.visualize_metrics_dashboard(
    query_id=query_id,
    output_file="visualizations/latest_dashboard.html"
)

# Compare multiple queries
optimizer.visualize_performance_comparison(
    query_ids=[query_id1, query_id2],
    labels=["Original", "Optimized"],
    output_file="visualizations/optimization_comparison.png"
)

# Export metrics to CSV
optimizer.export_metrics_to_csv("all_query_metrics.csv")

# Get detailed performance analysis with metrics
performance_analysis = optimizer.analyze_performance()

# View bottlenecks
if "detailed_metrics" in performance_analysis:
    phases = performance_analysis["detailed_metrics"]["phase_breakdown"]
    sorted_phases = sorted(
        [(phase, stats["avg_duration"]) for phase, stats in phases.items()],
        key=lambda x: x[1],
        reverse=True
    )
    
    print("Top bottlenecks:")
    for phase, duration in sorted_phases[:3]:
        print(f"- {phase}: {duration:.3f}s")
```

## Visualization Types

### Phase Timing Visualization

Shows the time spent in each phase of query execution:

- Horizontal bar chart showing duration of each phase
- Phases sorted by duration (longest first)
- Includes timing for nested operations with proper hierarchy
- Color-coded by operation type (vector search, graph traversal, processing, etc.)
- Includes labels with exact duration values

### Query Plan Visualization

Displays the query execution plan as a directed graph:

- Nodes represent query operations
- Edges represent dependencies between operations
- Node size indicates cost or duration
- Node color indicates operation type
- Includes timing information for each node
- Shows the flow of execution from start to finish

### Resource Usage Visualization

Shows resource utilization during query execution:

- Time-series plot of memory usage (MB)
- Time-series plot of CPU usage (%)
- Vertical markers indicating phase boundaries
- Peak memory usage highlighted
- Average CPU utilization displayed

### Performance Comparison Visualization

Compares performance metrics across multiple queries:

- Multiple metrics shown across different queries
- Duration comparison with bar charts
- Memory usage comparison
- Phase-by-phase timing comparison
- Result quality and count comparison
- Summary statistics for easy comparison

### Query Patterns Visualization

Visualizes common query patterns from collected metrics:

- Pattern frequency chart
- Average duration by pattern
- Memory usage by pattern
- Identifies most expensive patterns
- Suggests optimization opportunities

### Interactive Dashboard

Generates a comprehensive HTML dashboard with all visualizations:

- Summary of query performance
- Phase timing breakdown
- Resource usage charts
- Optimization recommendations
- Detailed metrics tables
- Historical performance trends

## Best Practices for Query Performance Analysis

1. **Collect metrics consistently**: Enable metrics collection for all production queries to build a comprehensive performance profile
2. **Use hierarchical timing**: Structure your phase timing to capture nested operations for detailed analysis
3. **Track resource usage**: Enable resource tracking to identify memory-intensive operations
4. **Compare optimization strategies**: Use performance comparison to evaluate different optimization approaches
5. **Export metrics regularly**: Export metrics to CSV for long-term trend analysis
6. **Generate dashboards for complex issues**: Create comprehensive dashboards when investigating performance problems
7. **Focus on bottlenecks**: Prioritize optimization of the most time-consuming phases
8. **Monitor cache effectiveness**: Track cache hit rates and savings through performance metrics
9. **Correlate query features and performance**: Analyze how query parameters affect performance metrics
10. **Implement recommendations**: Apply the optimization recommendations generated from the performance analysis

### Vector Query Optimization

1. **Index Selection**: Choose the appropriate index type based on your dataset size and query requirements
2. **Parameter Tuning**: Tune search parameters for the right balance between speed and accuracy
3. **Quantization**: Consider vector quantization for large vector datasets
4. **Result Reranking**: Apply reranking for better precision in top results
5. **Multi-Model Approach**: Use multiple embedding models for improved results

### Graph Query Optimization

1. **Path Planning**: Plan traversal paths to minimize unnecessary exploration
2. **Index Creation**: Create indexes on frequently queried entity and relationship types
3. **Query Pattern Recognition**: Identify and optimize common query patterns
4. **Bidirectional Search**: Use bidirectional search for path queries
5. **Lazy Relationship Loading**: Load relationships only when needed

### GraphRAG Query Optimization

1. **Query Type Detection**: Detect query type to apply appropriate optimization
2. **Hybrid Weight Tuning**: Tune the weights of vector and graph components
3. **Entity-Centric Traversal**: Focus traversal on entities relevant to the query
4. **Progressive Retrieval**: Retrieve and process in stages for efficiency
5. **Path Pruning**: Prune traversal paths that are unlikely to be relevant

### IPLD-Specific Optimizations

1. **DAG Traversal Strategy**: Use specialized traversal algorithms for IPLD DAGs
2. **CID Path Optimization**: Optimize traversal using CID path patterns
3. **Block Batch Loading**: Load multiple blocks in batches by prefix
4. **Path Caching**: Cache traversal paths for improved performance
5. **Vector Dimensionality Reduction**: Optimize vector storage and comparison for IPLD

### Distributed Query Optimization

1. **Node Selection**: Select optimal nodes based on query characteristics
2. **Data Locality**: Exploit data locality to minimize network traffic
3. **Parallel Execution**: Execute query parts in parallel when possible
4. **Result Aggregation**: Efficiently aggregate distributed query results
5. **Communication Optimization**: Minimize data transfer between nodes

### General Query Optimization

1. **Query Planning**: Generate and evaluate alternative query plans
2. **Result Caching**: Cache query results for repeated access
3. **Performance Monitoring**: Monitor and analyze query performance
4. **Parameter Tuning**: Tune optimization parameters based on performance data
5. **Query Rewriting**: Rewrite queries for better execution plans

By applying these query optimization techniques, you can significantly improve the performance of your queries in IPFS Datasets Python, especially for complex queries over large datasets.