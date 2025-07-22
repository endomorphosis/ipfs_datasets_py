"""
Example demonstrating the use of RAG Query Optimizers for both Wikipedia and IPLD-based knowledge graphs.

This example shows how to use:
1. The WikipediaKnowledgeGraphOptimizer for Wikipedia-derived knowledge graphs
2. The IPLDGraphRAGQueryOptimizer for IPLD-based knowledge graphs
3. The UnifiedGraphRAGQueryOptimizer for mixed environments
"""

import numpy as np
import time
import sys
import os
from typing import Dict, Any, List

# Ensure the parent directory is in the Python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from ipfs_datasets_py.llm.llm_reasoning_tracer import WikipediaKnowledgeGraphTracer
from ipfs_datasets_py.rag.rag_query_optimizer import (
    WikipediaKnowledgeGraphOptimizer,
    IPLDGraphRAGQueryOptimizer,
    UnifiedGraphRAGQueryOptimizer
)

def print_section(title: str) -> None:
    """Print a section title with formatting."""
    print("\n" + "=" * 80)
    print(f"  {title}")
    print("=" * 80 + "\n")

def print_plan(plan: Dict[str, Any], indent: int = 2) -> None:
    """Print a plan with nice formatting."""
    indent_str = " " * indent
    for key, value in plan.items():
        if isinstance(value, dict):
            print(f"{indent_str}{key}:")
            print_plan(value, indent + 2)
        elif isinstance(value, list):
            print(f"{indent_str}{key}: [list with {len(value)} items]")
        else:
            print(f"{indent_str}{key}: {value}")

def wikipedia_optimizer_example() -> None:
    """Example of using the Wikipedia-specific optimizer."""
    print_section("Wikipedia Knowledge Graph Optimizer Example")

    # Create a mock tracer for demonstration purposes
    class MockWikipediaTracer(WikipediaKnowledgeGraphTracer):
        def __init__(self):
            super().__init__()
            self.query_plans = {}

        def get_trace_info(self, trace_id):
            # Return mock data for demonstration
            return {
                "page_title": "Example Page",
                "status": "completed",
                "extraction_temperature": 0.7,
                "structure_temperature": 0.5,
                "validation": {
                    "coverage": 0.8,
                    "edge_confidence": {
                        "instance_of": 0.9,
                        "related_to": 0.7,
                        "works_for": 0.6,
                        "located_in": 0.5
                    }
                },
                "knowledge_graph": {
                    "entities": [
                        {"entity_id": "e1", "name": "Microsoft", "entity_type": "organization"},
                        {"entity_id": "e2", "name": "Bill Gates", "entity_type": "person"}
                    ],
                    "relationships": [
                        {"source": "e2", "target": "e1", "type": "founded", "confidence": 0.9}
                    ]
                }
            }

        def record_query_plan(self, trace_id, plan):
            # Store the query plan
            self.query_plans[trace_id] = plan

    # Initialize tracer and optimizer with mock implementation
    tracer = MockWikipediaTracer()
    optimizer = WikipediaKnowledgeGraphOptimizer(tracer=tracer)

    # Mock a trace_id that would be returned from knowledge graph extraction
    trace_id = "wikipedia-trace-123456"

    # Create a query vector (in a real scenario this would be from an embedding model)
    query_vector = np.random.rand(768)

    # Example 1: Simple query optimization
    print("Example 1: Simple query optimization")
    query_text = "Who founded Microsoft and what products did they create?"

    # Optimize the query
    print(f"Optimizing query: \"{query_text}\"")
    plan = optimizer.optimize_query(
        query_text=query_text,
        query_vector=query_vector,
        trace_id=trace_id
    )

    # Print the optimized plan
    print("\nOptimized Query Plan:")
    print_plan(plan)

    # Example 2: Query with specific entity types
    print("\nExample 2: Query with specific entity types")
    entity_types = ["person", "organization", "technology"]

    # Optimize the query with entity types
    print(f"Optimizing query with entity types: {entity_types}")
    plan = optimizer.optimize_query(
        query_text=query_text,
        query_vector=query_vector,
        entity_types=entity_types,
        trace_id=trace_id
    )

    # Print the optimized plan
    print("\nOptimized Query Plan:")
    print_plan(plan)

    # Example 3: Cross-document query
    print("\nExample 3: Cross-document query")
    doc_trace_ids = ["trace-microsoft", "trace-windows", "trace-office"]

    # Optimize a cross-document query
    print("Optimizing cross-document query across Microsoft, Windows, and Office pages")
    plan = optimizer.optimize_cross_document_query(
        query_text="How did Microsoft's development of Windows influence Office products?",
        query_vector=query_vector,
        doc_trace_ids=doc_trace_ids
    )

    # Print the optimized plan
    print("\nCross-Document Query Plan:")
    print_plan(plan)

def ipld_optimizer_example() -> None:
    """Example of using the IPLD-specific optimizer."""
    print_section("IPLD-Based Knowledge Graph Optimizer Example")

    # Initialize optimizer
    optimizer = IPLDGraphRAGQueryOptimizer(
        vector_weight=0.6,
        graph_weight=0.4,
        enable_multihash_prefetching=True,
        enable_block_batching=True,
        dag_traversal_strategy="breadth_first"
    )

    # Create a query vector (in a real scenario this would be from an embedding model)
    query_vector = np.random.rand(768)

    # Example 1: Content-type specific optimization
    print("Example 1: Content-type specific optimization")
    content_types = ["application/json", "application/ld+json"]

    # Optimize the query with content types
    print(f"Optimizing query for content types: {content_types}")
    plan = optimizer.optimize_query(
        query_vector=query_vector,
        query_text="How does IPFS implement content addressing?",
        content_types=content_types,
        root_cids=["QmXoypizjW3WknFiJnKLwHCnL72vedxjQkDDP1mXWo6uco"]
    )

    # Print the optimized plan
    print("\nOptimized Query Plan:")
    print_plan(plan)

    # Example 2: Multi-CID optimization
    print("\nExample 2: Multi-CID optimization")
    root_cids = [
        "QmXoypizjW3WknFiJnKLwHCnL72vedxjQkDDP1mXWo6uco",  # IPFS docs
        "QmYwAPJzv5CZsnA625s3Xf2nemtYgPpHdWEz79ojWnPbdG",  # Libp2p docs
        "QmZ4tDuvesekSs4qM5ZBKpXiZGun7S2CYtEZRB3DYXkjGx"   # Filecoin docs
    ]

    # Optimize the query with multiple CIDs
    print(f"Optimizing query across {len(root_cids)} different documents")
    plan = optimizer.optimize_query(
        query_vector=query_vector,
        query_text="Compare DHT implementations across IPFS, libp2p, and Filecoin",
        root_cids=root_cids
    )

    # Print the optimized plan
    print("\nMulti-CID Query Plan:")
    print_plan(plan)

    # Example 3: Multi-graph query optimization
    print("\nExample 3: Multi-graph query optimization")

    # Optimize a multi-graph query
    print("Optimizing query across multiple IPLD graphs")
    plan = optimizer.optimize_multi_graph_query(
        query_vector=query_vector,
        query_text="How do distributed hash tables compare to other distributed data structures?",
        graph_cids=root_cids
    )

    # Print the optimized plan
    print("\nMulti-Graph Query Plan:")
    print_plan(plan)

    # Example 4: Content-type specific weights
    print("\nExample 4: Content-type specific weights")
    content_types = ["text/plain", "application/json", "text/html", "image/png"]

    # Print optimized weights for each content type
    for content_type in content_types:
        weights = optimizer.optimize_for_content_type(content_type)
        print(f"  {content_type}: vector={weights['vector']:.2f}, graph={weights['graph']:.2f}")

def unified_optimizer_example() -> None:
    """Example of using the Unified optimizer for mixed environments."""
    print_section("Unified GraphRAG Query Optimizer Example")

    # Create a mock tracer for demonstration purposes
    class MockWikipediaTracer(WikipediaKnowledgeGraphTracer):
        def __init__(self):
            super().__init__()
            self.query_plans = {}

        def get_trace_info(self, trace_id):
            # Return mock data for demonstration
            return {
                "page_title": "Example Page",
                "status": "completed",
                "extraction_temperature": 0.7,
                "structure_temperature": 0.5,
                "validation": {
                    "coverage": 0.8,
                    "edge_confidence": {
                        "instance_of": 0.9,
                        "related_to": 0.7,
                        "works_for": 0.6,
                        "located_in": 0.5
                    }
                }
            }

        def record_query_plan(self, trace_id, plan):
            # Store the query plan
            self.query_plans[trace_id] = plan

    # Initialize components
    tracer = MockWikipediaTracer()
    wikipedia_optimizer = WikipediaKnowledgeGraphOptimizer(tracer=tracer)
    ipld_optimizer = IPLDGraphRAGQueryOptimizer()

    # Create unified optimizer
    optimizer = UnifiedGraphRAGQueryOptimizer(
        wikipedia_optimizer=wikipedia_optimizer,
        ipld_optimizer=ipld_optimizer,
        auto_detect_graph_type=True
    )

    # Create a query vector
    query_vector = np.random.rand(768)
    query_text = "Compare distributed storage approaches in decentralized systems"

    # Example 1: Auto-detection of graph type
    print("Example 1: Auto-detection of graph type")

    # Wikipedia query (detected by trace_id)
    print("Wikipedia query (with trace_id):")
    wiki_plan = optimizer.optimize_query(
        query_vector=query_vector,
        query_text=query_text,
        trace_id="wikipedia-trace-123"
    )
    print(f"  Detected optimizer type: {wiki_plan.get('optimizer_type', 'unknown')}")

    # IPLD query (detected by root_cids)
    print("\nIPLD query (with root_cids):")
    ipld_plan = optimizer.optimize_query(
        query_vector=query_vector,
        query_text=query_text,
        root_cids=["QmXoypizjW3WknFiJnKLwHCnL72vedxjQkDDP1mXWo6uco"]
    )
    print(f"  Detected optimizer type: {ipld_plan.get('optimizer_type', 'unknown')}")

    # Example 2: Explicit graph type specification
    print("\nExample 2: Explicit graph type specification")

    # Force Wikipedia optimizer
    print("Forcing Wikipedia optimizer with graph_type='wikipedia':")
    force_wiki_plan = optimizer.optimize_query(
        query_vector=query_vector,
        query_text=query_text,
        root_cids=["QmXoypizjW3WknFiJnKLwHCnL72vedxjQkDDP1mXWo6uco"],  # Would normally trigger IPLD
        graph_type="wikipedia"  # Force Wikipedia
    )
    print(f"  Optimizer type: {force_wiki_plan.get('optimizer_type', 'unknown')}")

    # Example 3: Multi-graph query with mixed types
    print("\nExample 3: Multi-graph query with mixed types")

    # Define graph specifications
    graph_specs = [
        {
            "graph_type": "wikipedia",
            "trace_id": "wiki-123",
            "weight": 0.4
        },
        {
            "graph_type": "ipld",
            "root_cid": "QmXoypizjW3WknFiJnKLwHCnL72vedxjQkDDP1mXWo6uco",
            "weight": 0.6
        }
    ]

    # Optimize multi-graph query
    print("Optimizing query across Wikipedia and IPLD graphs:")
    multi_plan = optimizer.optimize_multi_graph_query(
        query_vector=query_vector,
        query_text=query_text,
        graph_specs=graph_specs
    )

    # Print key aspects of the plan
    print(f"  Optimizer type: {multi_plan.get('optimizer_type', 'unknown')}")
    print(f"  Number of graph plans: {len(multi_plan.get('graph_plans', {}))}")

    # Check plan types
    graph_plans = multi_plan.get('graph_plans', {})
    for graph_id, plan in graph_plans.items():
        print(f"  - Graph {graph_id}: {plan.get('optimizer_type', 'unknown')}")

    # Print weights from combination plan
    combination_plan = multi_plan.get('combination_plan', {})
    weights = combination_plan.get('graph_weights', {})
    print("  Graph weights:")
    for graph_id, weight in weights.items():
        print(f"  - {graph_id}: {weight:.2f}")

    # Example 4: Get optimizer statistics
    print("\nExample 4: Get optimizer statistics")

    # Create and run a few more queries
    for _ in range(3):
        optimizer.optimize_query(
            query_vector=np.random.rand(768),
            query_text="Random query for stats",
            trace_id=f"wiki-{np.random.randint(1000)}"
        )

    for _ in range(2):
        optimizer.optimize_query(
            query_vector=np.random.rand(768),
            query_text="Another random query",
            root_cids=[f"Qm{np.random.randint(1000)}"]
        )

    # Get and print statistics
    stats = optimizer.get_optimization_stats()
    print("Optimizer Statistics:")
    print(f"  Total queries: {stats.get('total_queries', 0)}")
    print(f"  Wikipedia queries: {stats.get('wikipedia_queries', 0)} " +
          f"({stats.get('wikipedia_percentage', 0):.1f}%)")
    print(f"  IPLD queries: {stats.get('ipld_queries', 0)} " +
          f"({stats.get('ipld_percentage', 0):.1f}%)")
    print(f"  Mixed queries: {stats.get('mixed_queries', 0)} " +
          f"({stats.get('mixed_percentage', 0):.1f}%)")

    # Example 5: Performance analysis
    print("\nExample 5: Performance analysis")

    analysis = optimizer.analyze_query_performance()
    print("Performance Analysis:")
    print("  Recommendations:")
    for i, rec in enumerate(analysis.get('recommendations', [])):
        print(f"  {i+1}. {rec}")

def run_all_examples() -> None:
    """Run all optimizer examples."""
    wikipedia_optimizer_example()
    ipld_optimizer_example()
    unified_optimizer_example()

if __name__ == "__main__":
    run_all_examples()
