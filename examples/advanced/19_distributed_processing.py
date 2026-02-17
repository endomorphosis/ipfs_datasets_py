"""
Distributed Processing - P2P Networking and Decentralized Compute

This example demonstrates distributed processing capabilities including P2P
networking, decentralized compute, distributed datasets, and IPFS integration
for scalable, resilient data processing.

Requirements:
    - ipfs_kit_py: For IPFS integration
    - ipfshttpclient: pip install ipfshttpclient
    - Optional: IPFS daemon running locally

Usage:
    python examples/advanced/19_distributed_processing.py
"""

import asyncio


async def demo_p2p_dataset_loading():
    """Load datasets from P2P network."""
    print("\n" + "="*70)
    print("DEMO 1: P2P Dataset Loading")
    print("="*70)
    
    print("\n🌐 P2P Dataset Loading")
    print("   Load datasets from IPFS and other P2P protocols")
    
    example_code = '''
from ipfs_datasets_py import DatasetManager

manager = DatasetManager(
    storage_backend="ipfs",
    ipfs_gateway="http://localhost:5001"
)

# Load dataset from IPFS CID
cid = "QmYwAPJzv5CZsnA625s3Xf2nemtYgPpHdWEz79ojWnPbdG"
dataset = await manager.load_from_ipfs(
    cid=cid,
    verify_hash=True,
    pin_local=True  # Pin to local IPFS node
)

print(f"Dataset loaded from IPFS:")
print(f"  CID: {dataset.cid}")
print(f"  Size: {dataset.size_mb} MB")
print(f"  Rows: {len(dataset)}")
print(f"  Columns: {list(dataset.columns)}")

# Load from multiple sources with fallback
dataset = await manager.load_distributed(
    sources=[
        {"type": "ipfs", "cid": cid},
        {"type": "http", "url": "https://example.com/data.parquet"},
        {"type": "local", "path": "./cache/data.parquet"}
    ],
    prefer_local=True,
    fallback_enabled=True
)

# Stream large datasets
async for batch in manager.stream_from_ipfs(cid, batch_size=1000):
    print(f"Processing batch: {len(batch)} rows")
    # Process batch...
    '''
    
    print(example_code)


async def demo_distributed_embedding():
    """Generate embeddings across multiple nodes."""
    print("\n" + "="*70)
    print("DEMO 2: Distributed Embedding Generation")
    print("="*70)
    
    print("\n🔢 Distributed Embeddings")
    print("   Scale embedding generation across P2P network")
    
    example_code = '''
from ipfs_datasets_py.ml import DistributedEmbedder

embedder = DistributedEmbedder(
    model_name="sentence-transformers/all-MiniLM-L6-v2",
    nodes=[
        "ipfs://node1.example.com",
        "ipfs://node2.example.com",
        "ipfs://node3.example.com"
    ],
    load_balancing="round_robin"  # or "least_loaded", "random"
)

# Large corpus to embed
texts = [
    "Text 1...",
    "Text 2...",
    # ... 10,000+ texts
]

# Distribute work across nodes
embeddings = await embedder.embed_distributed(
    texts=texts,
    batch_size=100,
    show_progress=True
)

print(f"Generated {len(embeddings)} embeddings")
print(f"Distribution:")
for node, count in embedder.get_node_stats().items():
    print(f"  {node}: {count} embeddings")

# Results stored on IPFS
cid = await embedder.store_results(embeddings)
print(f"Results stored at: {cid}")

# Retrieve from any node
embeddings_retrieved = await embedder.load_from_ipfs(cid)
    '''
    
    print(example_code)


async def demo_p2p_vector_search():
    """Distributed vector search across nodes."""
    print("\n" + "="*70)
    print("DEMO 3: P2P Vector Search")
    print("="*70)
    
    print("\n🔍 P2P Vector Search")
    print("   Search vectors across distributed nodes")
    
    example_code = '''
from ipfs_datasets_py.vector_stores import DistributedVectorStore

store = DistributedVectorStore(
    backend="ipld",  # IPLD for IPFS-native storage
    nodes=[
        "node1.ipfs.io",
        "node2.ipfs.io",
        "node3.ipfs.io"
    ],
    replication_factor=2  # Replicate across 2 nodes
)

# Add vectors across network
vectors = generate_embeddings(texts)
await store.add_distributed(
    vectors=vectors,
    metadata=metadata,
    partition_by="topic"  # Partition by topic
)

# Search across all nodes
query_vector = generate_embedding("search query")
results = await store.search_distributed(
    query_vector=query_vector,
    top_k=10,
    merge_strategy="score_weighted"
)

print(f"Search results from {len(results.nodes_searched)} nodes:")
for result in results.results:
    print(f"  {result.text} (score: {result.score:.3f})")
    print(f"  Node: {result.source_node}")

# Statistics
print(f"\\nSearch statistics:")
print(f"  Total searched: {results.total_searched:,} vectors")
print(f"  Search time: {results.search_time_ms}ms")
print(f"  Network latency: {results.network_latency_ms}ms")
    '''
    
    print(example_code)


async def demo_distributed_knowledge_graph():
    """Distributed knowledge graph across IPFS."""
    print("\n" + "="*70)
    print("DEMO 4: Distributed Knowledge Graph")
    print("="*70)
    
    print("\n🕸️  Distributed Knowledge Graph")
    print("   Build and query graphs across P2P network")
    
    example_code = '''
from ipfs_datasets_py.knowledge_graphs import DistributedKnowledgeGraph

graph = DistributedKnowledgeGraph(
    storage="ipld",
    partition_strategy="domain"  # domain, geographic, or hash
)

# Build graph across nodes
documents = load_documents()
await graph.build_distributed(
    documents=documents,
    extraction_model="local",  # Run extraction on each node
    merge_strategy="consensus"  # Merge with consensus
)

print(f"Distributed graph:")
print(f"  Entities: {len(graph.entities):,}")
print(f"  Relationships: {len(graph.relationships):,}")
print(f"  Partitions: {graph.partition_count}")

# Query across partitions
results = await graph.query(
    query="Find all Person entities related to 'AI'",
    max_hops=3,
    parallel=True
)

print(f"\\nQuery results: {len(results)}")

# Each partition can be accessed independently via CID
for partition_id, cid in graph.get_partition_cids().items():
    print(f"  Partition {partition_id}: {cid}")

# Synchronize changes across nodes
await graph.sync(
    conflict_resolution="latest",
    verify_integrity=True
)
    '''
    
    print(example_code)


async def demo_decentralized_compute():
    """Run compute jobs on P2P network."""
    print("\n" + "="*70)
    print("DEMO 5: Decentralized Compute")
    print("="*70)
    
    print("\n⚡ Decentralized Compute")
    print("   Distribute computation across network")
    
    example_code = '''
from ipfs_datasets_py.compute import DecentralizedCompute

compute = DecentralizedCompute(
    protocol="ipfs_accelerate",  # or "libp2p"
    max_workers=10
)

# Define computation task
task = {
    "type": "embedding_generation",
    "model": "sentence-transformers/all-MiniLM-L6-v2",
    "input_cid": "QmXxx...",  # Input data on IPFS
    "output_format": "parquet"
}

# Submit to network
job = await compute.submit_job(
    task=task,
    resource_requirements={
        "gpu": False,
        "memory_gb": 4,
        "cpu_cores": 2
    },
    timeout_minutes=30
)

print(f"Job submitted: {job.id}")
print(f"Estimated cost: {job.estimated_cost} tokens")

# Monitor progress
async for update in compute.monitor_job(job.id):
    print(f"Progress: {update.progress:.1%}")
    print(f"Status: {update.status}")
    if update.errors:
        print(f"Errors: {update.errors}")

# Get results
result = await compute.get_result(job.id)

print(f"\\nJob complete:")
print(f"  Output CID: {result.output_cid}")
print(f"  Execution time: {result.execution_time_sec}s")
print(f"  Cost: {result.actual_cost} tokens")

# Load results
output_data = await compute.load_output(result.output_cid)
    '''
    
    print(example_code)


async def demo_p2p_caching():
    """Distributed caching across nodes."""
    print("\n" + "="*70)
    print("DEMO 6: P2P Caching")
    print("="*70)
    
    print("\n💾 P2P Caching")
    print("   Cache results across network for faster access")
    
    example_code = '''
from ipfs_datasets_py.caching import DistributedCache

cache = DistributedCache(
    protocol="ipfs",
    cache_size_gb=10,
    ttl_hours=24,
    replication=2
)

# Cache expensive computation
@cache.cached(key_func=lambda x: x["query"])
async def expensive_operation(params):
    # Expensive embedding + search
    embeddings = generate_embeddings(params["query"])
    results = search_vector_store(embeddings)
    return results

# First call - cache miss (slow)
results1 = await expensive_operation({"query": "AI research"})
print(f"Cache miss - took {results1.execution_time}ms")

# Second call - cache hit (fast)
results2 = await expensive_operation({"query": "AI research"})
print(f"Cache hit - took {results2.execution_time}ms")

# Cache statistics
stats = await cache.get_stats()
print(f"\\nCache statistics:")
print(f"  Hits: {stats.hits}")
print(f"  Misses: {stats.misses}")
print(f"  Hit rate: {stats.hit_rate:.1%}")
print(f"  Total size: {stats.size_mb} MB")
print(f"  Nodes: {len(stats.nodes)}")

# Manually cache data
await cache.set(
    key="popular_query_results",
    value=results,
    ttl_hours=48,
    replicate_to=3  # Replicate to 3 nodes
)

# Retrieve from cache
cached_results = await cache.get("popular_query_results")
    '''
    
    print(example_code)


async def demo_resilient_pipeline():
    """Build resilient processing pipeline."""
    print("\n" + "="*70)
    print("DEMO 7: Resilient Distributed Pipeline")
    print("="*70)
    
    print("\n🔄 Resilient Pipeline")
    print("   Fault-tolerant distributed data pipeline")
    
    example_code = '''
from ipfs_datasets_py.pipelines import DistributedPipeline

pipeline = DistributedPipeline(
    storage="ipfs",
    compute="decentralized",
    fault_tolerance="retry_on_failure"
)

# Define pipeline stages
await pipeline.add_stage(
    name="load",
    function=load_from_ipfs,
    inputs=["cid"],
    outputs=["raw_data"]
)

await pipeline.add_stage(
    name="preprocess",
    function=preprocess_data,
    inputs=["raw_data"],
    outputs=["clean_data"],
    distributed=True  # Run on multiple nodes
)

await pipeline.add_stage(
    name="embed",
    function=generate_embeddings,
    inputs=["clean_data"],
    outputs=["embeddings"],
    requires_gpu=False
)

await pipeline.add_stage(
    name="index",
    function=build_vector_index,
    inputs=["embeddings"],
    outputs=["index_cid"]
)

# Execute pipeline
result = await pipeline.execute(
    input_cid="QmXxx...",
    checkpoint_enabled=True,  # Save checkpoints
    retry_failed=True,
    max_retries=3
)

print(f"Pipeline execution:")
print(f"  Status: {result.status}")
print(f"  Total time: {result.total_time_sec}s")
print(f"  Output CID: {result.output_cid}")

# Stage statistics
for stage_name, stats in result.stage_stats.items():
    print(f"\\n{stage_name}:")
    print(f"  Time: {stats.time_sec}s")
    print(f"  Retries: {stats.retry_count}")
    print(f"  Nodes used: {stats.node_count}")

# Resume from checkpoint if failed
if result.status == "failed":
    result = await pipeline.resume(
        checkpoint_cid=result.last_checkpoint_cid
    )
    '''
    
    print(example_code)


async def demo_ipfs_pinning_strategy():
    """Strategic IPFS pinning for availability."""
    print("\n" + "="*70)
    print("DEMO 8: IPFS Pinning Strategy")
    print("="*70)
    
    print("\n📌 Pinning Strategy")
    print("   Ensure data availability across network")
    
    example_code = '''
from ipfs_datasets_py.ipfs import PinningStrategy

strategy = PinningStrategy(
    local_node="http://localhost:5001",
    pinning_services=[
        {"name": "pinata", "api_key": "xxx"},
        {"name": "web3.storage", "api_key": "yyy"}
    ]
)

# Pin important data
cid = "QmXxx..."
pins = await strategy.pin_with_redundancy(
    cid=cid,
    redundancy_level=3,  # Pin on 3 services
    priority="high"
)

print(f"Pinned CID {cid}:")
for pin in pins:
    print(f"  {pin.service}: {pin.status}")

# Monitor pin health
health = await strategy.check_pin_health(cid)
print(f"\\nPin health:")
print(f"  Active pins: {health.active_count}")
print(f"  Failed pins: {health.failed_count}")
print(f"  Availability: {health.availability:.1%}")

# Auto-repair failed pins
if health.failed_count > 0:
    repaired = await strategy.repair_pins(
        cid=cid,
        target_redundancy=3
    )
    print(f"Repaired {len(repaired)} pins")

# Garbage collection strategy
await strategy.gc_unpinned(
    keep_recent_days=7,
    min_access_count=1,
    dry_run=True  # Preview what would be deleted
)
    '''
    
    print(example_code)


def show_tips():
    """Show tips for distributed processing."""
    print("\n" + "="*70)
    print("TIPS FOR DISTRIBUTED PROCESSING")
    print("="*70)
    
    print("\n1. IPFS Setup:")
    print("   - Install and run IPFS daemon locally")
    print("   - Configure for your network (public/private)")
    print("   - Use pinning services for redundancy")
    print("   - Monitor storage usage")
    
    print("\n2. Data Distribution:")
    print("   - Partition large datasets appropriately")
    print("   - Use content-addressing for deduplication")
    print("   - Implement smart caching strategies")
    print("   - Consider geographic distribution")
    
    print("\n3. Compute Distribution:")
    print("   - Balance load across available nodes")
    print("   - Handle node failures gracefully")
    print("   - Implement checkpointing for long jobs")
    print("   - Monitor resource usage")
    
    print("\n4. Network Considerations:")
    print("   - Network latency affects performance")
    print("   - Use local caching when possible")
    print("   - Implement timeout mechanisms")
    print("   - Test with realistic network conditions")
    
    print("\n5. Fault Tolerance:")
    print("   - Replicate critical data")
    print("   - Implement retry logic")
    print("   - Use checksums for verification")
    print("   - Maintain backups")
    
    print("\n6. Scalability:")
    print("   - Design for horizontal scaling")
    print("   - Avoid single points of failure")
    print("   - Use async/await for concurrency")
    print("   - Monitor and optimize bottlenecks")
    
    print("\n7. Security:")
    print("   - Verify content hashes")
    print("   - Use encryption for sensitive data")
    print("   - Implement access control")
    print("   - Audit data access")
    
    print("\n8. Cost Management:")
    print("   - Monitor storage costs")
    print("   - Implement data lifecycle policies")
    print("   - Use spot instances when possible")
    print("   - Cache frequently accessed data")
    
    print("\n9. Production Deployment:")
    print("   - Test thoroughly in staging")
    print("   - Monitor system health")
    print("   - Implement alerting")
    print("   - Document procedures")
    
    print("\n10. Next Steps:")
    print("    - See 06_ipfs_storage.py for IPFS basics")
    print("    - See 09_batch_processing.py for parallel processing")


async def main():
    """Run all distributed processing demonstrations."""
    print("\n" + "="*70)
    print("IPFS DATASETS PYTHON - DISTRIBUTED PROCESSING")
    print("="*70)
    
    await demo_p2p_dataset_loading()
    await demo_distributed_embedding()
    await demo_p2p_vector_search()
    await demo_distributed_knowledge_graph()
    await demo_decentralized_compute()
    await demo_p2p_caching()
    await demo_resilient_pipeline()
    await demo_ipfs_pinning_strategy()
    
    show_tips()
    
    print("\n" + "="*70)
    print("✅ DISTRIBUTED PROCESSING EXAMPLES COMPLETE")
    print("="*70)


if __name__ == "__main__":
    asyncio.run(main())
