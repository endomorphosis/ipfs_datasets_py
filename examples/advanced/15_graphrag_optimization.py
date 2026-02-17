"""
GraphRAG Optimization - Production-Ready Knowledge Graph RAG

This example demonstrates advanced GraphRAG optimization techniques including
ontology generation, query optimization, graph pruning, and performance tuning
for production deployments.

Requirements:
    - transformers, torch: pip install transformers torch
    - faiss-cpu: pip install faiss-cpu
    - Optional: neo4j for graph database

Usage:
    python examples/advanced/15_graphrag_optimization.py
"""

import asyncio
from pathlib import Path


async def demo_ontology_generation():
    """Generate optimized ontology from documents."""
    print("\n" + "="*70)
    print("DEMO 1: Automatic Ontology Generation")
    print("="*70)
    
    print("\n🏗️  Ontology Generation")
    print("   Automatically discover entity types and relationship schemas")
    
    example_code = '''
from ipfs_datasets_py.knowledge_graphs import OntologyGenerator

generator = OntologyGenerator(
    min_entity_frequency=5,      # Entities must appear 5+ times
    min_relation_confidence=0.7,  # Relationships need 70%+ confidence
    clustering_algorithm="hierarchical"
)

# Analyze document corpus
documents = load_document_corpus("./documents/")

# Generate ontology
ontology = await generator.generate(
    documents=documents,
    max_entity_types=50,
    max_relation_types=100
)

print(f"Generated ontology:")
print(f"  Entity types: {len(ontology.entity_types)}")
print(f"  Relation types: {len(ontology.relation_types)}")
print(f"  Constraints: {len(ontology.constraints)}")

# View entity type hierarchy
for entity_type in ontology.entity_types:
    print(f"\\n{entity_type.name}:")
    print(f"  Parent: {entity_type.parent}")
    print(f"  Attributes: {', '.join(entity_type.attributes)}")
    print(f"  Examples: {', '.join(entity_type.examples[:3])}")

# Export ontology
ontology.export("ontology.owl", format="owl")  # Web Ontology Language
ontology.export("ontology.json", format="json")
    '''
    
    print(example_code)


async def demo_graph_schema_optimization():
    """Optimize knowledge graph schema."""
    print("\n" + "="*70)
    print("DEMO 2: Graph Schema Optimization")
    print("="*70)
    
    print("\n⚙️  Schema Optimization")
    print("   Improve query performance with optimized schema")
    
    example_code = '''
from ipfs_datasets_py.knowledge_graphs import GraphSchemaOptimizer

optimizer = GraphSchemaOptimizer()

# Analyze query patterns
query_log = [
    "Find all entities of type Person",
    "Get relationships between Person and Organization",
    "Search for entities in location California",
    # ... more queries
]

# Generate optimization recommendations
recommendations = await optimizer.analyze(
    graph=knowledge_graph,
    query_patterns=query_log,
    usage_stats={"avg_queries_per_second": 100}
)

print("Optimization recommendations:")
for rec in recommendations:
    print(f"\\n{rec.type}: {rec.description}")
    print(f"  Expected improvement: {rec.expected_speedup}x")
    print(f"  Implementation: {rec.implementation}")

# Apply optimizations
for rec in recommendations:
    if rec.priority == "high":
        await optimizer.apply(graph, rec)
        print(f"✅ Applied: {rec.type}")

# Common optimizations:
# - Add indexes on frequently queried properties
# - Denormalize for common join patterns
# - Cache frequent subgraph queries
# - Partition by geographic region or domain
    '''
    
    print(example_code)


async def demo_graph_pruning():
    """Prune irrelevant nodes and edges."""
    print("\n" + "="*70)
    print("DEMO 3: Graph Pruning and Compression")
    print("="*70)
    
    print("\n✂️  Graph Pruning")
    print("   Remove noise and irrelevant information")
    
    example_code = '''
from ipfs_datasets_py.knowledge_graphs import GraphPruner

pruner = GraphPruner(
    min_node_degree=2,        # Remove nodes with <2 connections
    min_edge_weight=0.5,      # Remove weak relationships
    keep_bridge_nodes=True    # Keep nodes that connect communities
)

# Prune graph
original_size = len(graph.entities)
pruned_graph = await pruner.prune(
    graph=graph,
    preserve_core=True,        # Keep core entities
    preserve_paths=True        # Maintain important paths
)

pruned_size = len(pruned_graph.entities)
reduction = (1 - pruned_size/original_size) * 100

print(f"Graph pruning results:")
print(f"  Original entities: {original_size:,}")
print(f"  Pruned entities: {pruned_size:,}")
print(f"  Reduction: {reduction:.1f}%")

# Quality metrics after pruning
quality = await pruner.assess_quality(
    original_graph=graph,
    pruned_graph=pruned_graph
)

print(f"\\nQuality metrics:")
print(f"  Information retention: {quality.information_retention:.1%}")
print(f"  Query performance: {quality.query_speedup:.1f}x faster")
print(f"  Storage savings: {quality.storage_reduction:.1%}")
    '''
    
    print(example_code)


async def demo_query_optimization():
    """Optimize GraphRAG queries."""
    print("\n" + "="*70)
    print("DEMO 4: Query Optimization")
    print("="*70)
    
    print("\n🚀 Query Optimization")
    print("   Optimize query execution for speed and relevance")
    
    example_code = '''
from ipfs_datasets_py.search import GraphRAGQueryOptimizer

optimizer = GraphRAGQueryOptimizer(
    cache_size=1000,           # Cache frequent queries
    max_expansion_depth=3,     # Limit graph traversal depth
    enable_parallel=True       # Parallel subquery execution
)

# Original query
query = "What companies were founded by people who studied at MIT?"

# Analyze query
analysis = await optimizer.analyze_query(query)

print(f"Query analysis:")
print(f"  Complexity: {analysis.complexity}")
print(f"  Expected hops: {analysis.expected_hops}")
print(f"  Estimated time: {analysis.estimated_ms}ms")

# Optimize query execution plan
plan = await optimizer.optimize(
    query=query,
    graph=knowledge_graph
)

print(f"\\nOptimized execution plan:")
for i, step in enumerate(plan.steps, 1):
    print(f"  {i}. {step.operation} ({step.estimated_ms}ms)")

# Execute optimized query
results = await optimizer.execute(
    query=query,
    plan=plan,
    graph=knowledge_graph
)

print(f"\\nResults: {len(results)} found")
print(f"Execution time: {results.execution_ms}ms")

# Cache for future queries
optimizer.cache_result(query, results)
    '''
    
    print(example_code)


async def demo_incremental_updates():
    """Handle incremental graph updates efficiently."""
    print("\n" + "="*70)
    print("DEMO 5: Incremental Updates")
    print("="*70)
    
    print("\n📈 Incremental Updates")
    print("   Add new data without full rebuild")
    
    example_code = '''
from ipfs_datasets_py.knowledge_graphs import IncrementalGraphBuilder

builder = IncrementalGraphBuilder(
    graph=knowledge_graph,
    merge_strategy="smart",      # smart, replace, or append
    conflict_resolution="latest"  # latest, highest_confidence, manual
)

# Add new documents incrementally
new_documents = [
    "New research from Stanford shows...",
    "Apple announced a new product today...",
]

# Extract and merge new entities/relationships
updates = await builder.add_documents(
    documents=new_documents,
    batch_size=10,
    verify_consistency=True
)

print(f"Incremental update results:")
print(f"  New entities: {updates.entities_added}")
print(f"  New relationships: {updates.relationships_added}")
print(f"  Updated entities: {updates.entities_updated}")
print(f"  Conflicts resolved: {updates.conflicts_resolved}")

# Handle conflicts
if updates.conflicts:
    for conflict in updates.conflicts:
        print(f"\\nConflict detected:")
        print(f"  Entity: {conflict.entity}")
        print(f"  Old value: {conflict.old_value}")
        print(f"  New value: {conflict.new_value}")
        
        # Resolve with strategy
        resolution = await builder.resolve_conflict(
            conflict=conflict,
            strategy="highest_confidence"
        )
        print(f"  Resolution: {resolution.chosen_value}")

# Rebuild indexes only for affected parts
await builder.rebuild_indexes(incremental=True)
    '''
    
    print(example_code)


async def demo_distributed_graphrag():
    """Scale GraphRAG across multiple nodes."""
    print("\n" + "="*70)
    print("DEMO 6: Distributed GraphRAG")
    print("="*70)
    
    print("\n🌐 Distributed GraphRAG")
    print("   Scale to billions of entities")
    
    example_code = '''
from ipfs_datasets_py.search import DistributedGraphRAG

# Setup distributed system
graphrag = DistributedGraphRAG(
    nodes=[
        "node1.example.com:5000",
        "node2.example.com:5000",
        "node3.example.com:5000"
    ],
    partition_strategy="domain",  # domain, geographic, or hash
    replication_factor=2
)

# Partition graph across nodes
await graphrag.partition_graph(
    graph=large_knowledge_graph,
    partition_key="domain"  # e.g., tech, legal, medical
)

print("Graph distribution:")
for node in graphrag.nodes:
    stats = await node.get_stats()
    print(f"  {node.address}:")
    print(f"    Entities: {stats.entity_count:,}")
    print(f"    Relationships: {stats.relationship_count:,}")
    print(f"    Storage: {stats.storage_mb} MB")

# Distributed query
query = "Find all connections between Person and Organization"
results = await graphrag.query(
    query=query,
    max_hops=3,
    combine_results=True  # Merge results from all nodes
)

print(f"\\nDistributed query results:")
print(f"  Total results: {len(results)}")
print(f"  Nodes queried: {results.nodes_queried}")
print(f"  Total time: {results.total_ms}ms")
print(f"  Max node time: {results.max_node_ms}ms")
    '''
    
    print(example_code)


async def demo_performance_monitoring():
    """Monitor and tune GraphRAG performance."""
    print("\n" + "="*70)
    print("DEMO 7: Performance Monitoring")
    print("="*70)
    
    print("\n📊 Performance Monitoring")
    print("   Monitor and optimize in production")
    
    example_code = '''
from ipfs_datasets_py.search import GraphRAGMonitor

monitor = GraphRAGMonitor(
    graphrag=graphrag_system,
    metrics_interval=60,  # Collect metrics every 60s
    alert_threshold={"latency_p95": 1000}  # Alert if p95 > 1s
)

# Start monitoring
await monitor.start()

# Get real-time metrics
metrics = await monitor.get_metrics()

print("Current performance metrics:")
print(f"  Queries/sec: {metrics.qps:.1f}")
print(f"  Avg latency: {metrics.avg_latency_ms:.1f}ms")
print(f"  P50 latency: {metrics.p50_latency_ms:.1f}ms")
print(f"  P95 latency: {metrics.p95_latency_ms:.1f}ms")
print(f"  P99 latency: {metrics.p99_latency_ms:.1f}ms")
print(f"  Cache hit rate: {metrics.cache_hit_rate:.1%}")
print(f"  Error rate: {metrics.error_rate:.2%}")

# Get bottleneck analysis
bottlenecks = await monitor.analyze_bottlenecks()

print("\\nBottleneck analysis:")
for bottleneck in bottlenecks:
    print(f"  {bottleneck.component}: {bottleneck.impact}")
    print(f"    Recommendation: {bottleneck.recommendation}")

# Set up alerts
await monitor.add_alert(
    condition="p95_latency > 1000",
    action="notify",
    recipients=["ops@example.com"]
)

# Auto-tuning
tuner = monitor.get_auto_tuner()
await tuner.enable(
    parameters=["cache_size", "parallelism", "batch_size"]
)
    '''
    
    print(example_code)


def show_tips():
    """Show tips for GraphRAG optimization."""
    print("\n" + "="*70)
    print("TIPS FOR GRAPHRAG OPTIMIZATION")
    print("="*70)
    
    print("\n1. Ontology Design:")
    print("   - Start with automatic generation, refine manually")
    print("   - Keep entity types focused and specific")
    print("   - Use hierarchical types for flexibility")
    print("   - Define clear relationship semantics")
    
    print("\n2. Performance Optimization:")
    print("   - Index frequently queried properties")
    print("   - Cache common queries and subgraphs")
    print("   - Limit graph traversal depth")
    print("   - Use denormalization for hot paths")
    
    print("\n3. Graph Quality:")
    print("   - Prune low-confidence edges regularly")
    print("   - Validate against ground truth")
    print("   - Monitor entity/relationship distribution")
    print("   - Handle conflicts systematically")
    
    print("\n4. Scaling Strategies:")
    print("   - Partition by domain or geography")
    print("   - Use Neo4j or other graph DBs for large scale")
    print("   - Implement sharding for >100M entities")
    print("   - Consider read replicas for query load")
    
    print("\n5. Incremental Updates:")
    print("   - Update in batches, not one-by-one")
    print("   - Rebuild indexes incrementally")
    print("   - Version your graph snapshots")
    print("   - Implement rollback capability")
    
    print("\n6. Query Optimization:")
    print("   - Analyze slow queries regularly")
    print("   - Use query plan analysis")
    print("   - Implement query result caching")
    print("   - Consider materialized views")
    
    print("\n7. Monitoring:")
    print("   - Track latency percentiles (P50, P95, P99)")
    print("   - Monitor cache hit rates")
    print("   - Alert on error rate spikes")
    print("   - Log slow queries for analysis")
    
    print("\n8. Production Checklist:")
    print("   - Backup and disaster recovery")
    print("   - Security and access control")
    print("   - Rate limiting and throttling")
    print("   - Load testing and capacity planning")
    
    print("\n9. Next Steps:")
    print("   - See 12_graphrag_basic.py for fundamentals")
    print("   - See 16_logic_enhanced_rag.py for logic integration")


async def main():
    """Run all GraphRAG optimization demonstrations."""
    print("\n" + "="*70)
    print("IPFS DATASETS PYTHON - GRAPHRAG OPTIMIZATION")
    print("="*70)
    
    await demo_ontology_generation()
    await demo_graph_schema_optimization()
    await demo_graph_pruning()
    await demo_query_optimization()
    await demo_incremental_updates()
    await demo_distributed_graphrag()
    await demo_performance_monitoring()
    
    show_tips()
    
    print("\n" + "="*70)
    print("✅ GRAPHRAG OPTIMIZATION EXAMPLES COMPLETE")
    print("="*70)


if __name__ == "__main__":
    asyncio.run(main())
