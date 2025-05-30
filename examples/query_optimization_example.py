#!/usr/bin/env python3
"""
Query Optimization Example

This example demonstrates how to use the query optimizer to improve performance
for various types of queries, including vector searches, graph traversals,
and hybrid queries combining both.
"""

import os
import sys
import time
import numpy as np
import random
import json
from typing import Dict, List, Any, Tuple, Optional

# Add parent directory to path to import modules
parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(parent_dir)

# Import the query optimizer
from ipfs_datasets_py.query_optimizer import (
    create_query_optimizer, QueryOptimizer, VectorIndexOptimizer,
    KnowledgeGraphQueryOptimizer, HybridQueryOptimizer
)
from ipfs_datasets_py.ipfs_knn_index import IPFSKnnIndex

# For demo purposes, let's create a simple mock knowledge graph class
class SimpleKnowledgeGraph:
    """A simple knowledge graph implementation for demonstration."""

    def __init__(self, num_entities=1000, num_relationships=5000):
        """Create a mock knowledge graph with random entities and relationships."""
        self.entities = {}
        self.relationships = []
        entity_types = ["person", "organization", "location", "concept", "document"]
        relationship_types = ["knows", "works_for", "located_in", "related_to", "mentions"]

        print(f"Creating mock knowledge graph with {num_entities} entities and {num_relationships} relationships...")

        # Create entities
        for i in range(num_entities):
            entity_type = random.choice(entity_types)
            entity_id = f"{entity_type}_{i}"
            self.entities[entity_id] = {
                "id": entity_id,
                "type": entity_type,
                "name": f"{entity_type.capitalize()} {i}",
                "created_at": time.time() - random.randint(0, 1000000)
            }

        # Create relationships
        entity_ids = list(self.entities.keys())
        for i in range(num_relationships):
            source_id = random.choice(entity_ids)
            target_id = random.choice(entity_ids)
            if source_id != target_id:
                rel_type = random.choice(relationship_types)
                self.relationships.append({
                    "id": f"rel_{i}",
                    "type": rel_type,
                    "source": source_id,
                    "target": target_id
                })

    def query(self, params):
        """Execute a graph query with the given parameters."""
        start_time = time.time()

        if params.get("query_type") == "get_entity":
            # Simple entity retrieval
            entity_id = params.get("entity_id")
            result = self.entities.get(entity_id)
            scan_count = 1

        elif params.get("query_type") == "traverse":
            # Graph traversal
            start_type = params.get("start_entity_type")
            relationship_types = params.get("relationship_types", [])
            max_depth = params.get("max_depth", 1)
            limit = params.get("limit", 10)

            # Filter by entity type if specified
            if start_type:
                start_entities = [e for e in self.entities.values() if e["type"] == start_type]
            else:
                start_entities = list(self.entities.values())

            # Simulate more complex traversal with optimizations
            if "path_plan" in params:
                # Use the optimized path plan
                path_plan = params["path_plan"]
                # This is where real optimization would happen
                time.sleep(0.001)  # Simulate faster processing with optimization
            else:
                # Without optimization
                time.sleep(0.005)  # Simulate slower processing

            # Generate results
            results = []
            for start_entity in start_entities[:limit]:
                # Find connected entities up to max_depth
                connected = self._find_connected(
                    start_entity["id"],
                    relationship_types,
                    max_depth
                )

                if connected:
                    results.append({
                        "start_entity": start_entity,
                        "connected_entities": connected
                    })

                if len(results) >= limit:
                    break

            result = results
            scan_count = len(start_entities)

        else:
            # Unknown query type
            result = {"error": f"Unknown query type: {params.get('query_type')}"}
            scan_count = 0

        # Add scan count and processing time for metrics
        end_time = time.time()
        result_obj = result
        result_obj.scan_count = scan_count
        result_obj.processing_time = (end_time - start_time) * 1000  # ms

        return result_obj

    def _find_connected(self, entity_id, relationship_types, max_depth):
        """Find entities connected to the given entity."""
        if max_depth <= 0:
            return []

        # Find relationships from this entity
        outgoing = [r for r in self.relationships
                  if r["source"] == entity_id
                  and (not relationship_types or r["type"] in relationship_types)]

        connected = []
        for rel in outgoing:
            target_id = rel["target"]
            if target_id in self.entities:
                connected.append({
                    "relationship": rel,
                    "entity": self.entities[target_id]
                })

                # Recurse for next level if needed
                if max_depth > 1:
                    next_level = self._find_connected(
                        target_id,
                        relationship_types,
                        max_depth - 1
                    )
                    for item in next_level:
                        if item not in connected:
                            connected.append(item)

        return connected[:10]  # Limit depth expansion


def run_example():
    """Run the query optimization example."""
    print("=== Query Optimization Example ===")

    # Create the optimizers
    print("\nCreating query optimizers...")
    optimizers = create_query_optimizer(
        max_cache_size=100,
        collect_statistics=True,
        optimize_vectors=True,
        optimize_graphs=True,
        optimize_hybrid=True
    )

    base_optimizer = optimizers["base"]
    vector_optimizer = optimizers["vector"]
    graph_optimizer = optimizers["graph"]
    hybrid_optimizer = optimizers["hybrid"]

    # Register some indexes
    print("\nRegistering indexes...")
    base_optimizer.index_registry.register_index(
        name="vector_index_768",
        index_type="vector",
        fields=["vector"],
        metadata={"dimension": 768, "metric": "cosine"}
    )

    base_optimizer.index_registry.register_index(
        name="entity_type_index",
        index_type="btree",
        fields=["type"],
        metadata={"cardinality": 5}
    )

    base_optimizer.index_registry.register_index(
        name="relationship_index",
        index_type="graph",
        fields=["source", "target", "type"],
        metadata={"bidirectional": True}
    )

    # Create our data sources
    print("\nCreating data sources...")
    vector_index = IPFSKnnIndex(dimension=768, metric="cosine")

    # Generate some random vectors for the index
    num_vectors = 1000
    vectors = [np.random.rand(768).astype(np.float32) for _ in range(num_vectors)]
    metadata = [{"id": i, "name": f"Vector {i}"} for i in range(num_vectors)]

    # Add vectors to the index
    print(f"Adding {num_vectors} vectors to the index...")
    vector_index.add_vectors(vectors, metadata=metadata)

    # Create a knowledge graph
    knowledge_graph = SimpleKnowledgeGraph(num_entities=500, num_relationships=2000)

    # Define example queries
    print("\n=== Running Example Queries ===")

    # 1. Basic vector search (without optimization)
    print("\n1. Basic vector search without optimization:")
    query_vector = np.random.rand(768).astype(np.float32)

    start_time = time.time()
    vector_results = vector_index.search(query_vector, top_k=10)
    basic_time = time.time() - start_time

    print(f"Found {len(vector_results)} results in {basic_time*1000:.2f} ms")

    # 2. Optimized vector search
    print("\n2. Optimized vector search:")
    query_params = {
        "query_vector": query_vector,
        "top_k": 10,
        "dimension": 768
    }

    # First, get an optimized plan
    vector_plan = vector_optimizer.optimize_vector_search(query_params)
    print("Vector search optimization plan:")
    print(json.dumps(vector_plan, indent=2, default=str)[:500] + "...") # Truncated for readability

    # Execute the optimized query
    optimized_search_func = lambda params: vector_index.search(
        params["query_vector"],
        top_k=params.get("top_k", 10)
    )

    vector_result, vector_metrics = vector_optimizer.execute_vector_search(
        query_params=query_params,
        search_func=optimized_search_func
    )

    print(f"Found {len(vector_result)} results in {vector_metrics.duration_ms:.2f} ms")
    print(f"Optimized parameters: {json.dumps(vector_plan['vector_specific'], indent=2)}")

    # 3. Basic graph query
    print("\n3. Basic graph query without optimization:")
    start_time = time.time()
    basic_graph_params = {
        "query_type": "traverse",
        "start_entity_type": "person",
        "relationship_types": ["knows", "works_for"],
        "max_depth": 2,
        "limit": 5
    }
    basic_graph_result = knowledge_graph.query(basic_graph_params)
    basic_graph_time = time.time() - start_time

    print(f"Found {len(basic_graph_result)} paths in {basic_graph_time*1000:.2f} ms")

    # 4. Optimized graph query
    print("\n4. Optimized graph query:")
    graph_params = {
        "query_type": "traverse",
        "start_entity_type": "person",
        "relationship_types": ["knows", "works_for"],
        "max_depth": 2,
        "limit": 5
    }

    # Get an optimized plan
    graph_plan = graph_optimizer.optimize_graph_query(graph_params)
    print("Graph query optimization plan:")
    print(json.dumps(graph_plan, indent=2, default=str)[:500] + "...") # Truncated for readability

    # Execute the optimized query
    graph_result, graph_metrics = graph_optimizer.execute_graph_query(
        query_params=graph_params,
        query_func=knowledge_graph.query
    )

    print(f"Found {len(graph_result)} paths in {graph_metrics.duration_ms:.2f} ms")

    # 5. Hybrid query (combining vector and graph)
    print("\n5. Hybrid query (vector + graph):")
    hybrid_params = {
        "vector_component": {
            "query_vector": query_vector,
            "top_k": 10,
            "dimension": 768
        },
        "graph_component": {
            "query_type": "traverse",
            "start_entity_type": "person",
            "relationship_types": ["knows", "works_for"],
            "max_depth": 2,
            "limit": 5
        },
        "vector_weight": 0.6,
        "graph_weight": 0.4
    }

    # Get an optimized plan
    hybrid_plan = hybrid_optimizer.optimize_hybrid_query(hybrid_params)
    print("Hybrid query optimization plan:")
    print(json.dumps(hybrid_plan, indent=2, default=str)[:500] + "...") # Truncated for readability

    # Execute the optimized query
    def merge_results(vector_results, graph_results, vector_weight, graph_weight):
        """Merge vector and graph results."""
        # This would be a more sophisticated merging algorithm in production
        merged = []

        # Process vector results
        for i, result in enumerate(vector_results):
            score = result.score if hasattr(result, 'score') else 0.9 - (i * 0.1)
            merged.append({
                "source": "vector",
                "score": score * vector_weight,
                "data": result
            })

        # Process graph results
        for i, result in enumerate(graph_results):
            # Assign decreasing scores to graph results
            score = 0.9 - (i * 0.1)
            merged.append({
                "source": "graph",
                "score": score * graph_weight,
                "data": result
            })

        # Sort by combined score
        merged.sort(key=lambda x: x["score"], reverse=True)

        # Just return the merged results for simplicity
        return merged

    hybrid_result, hybrid_metrics = hybrid_optimizer.execute_hybrid_query(
        query_params=hybrid_params,
        vector_func=optimized_search_func,
        graph_func=knowledge_graph.query,
        merge_func=merge_results
    )

    print(f"Found {len(hybrid_result)} combined results in {hybrid_metrics.duration_ms:.2f} ms")
    print(f"Combined metrics: {json.dumps(hybrid_metrics.execution_plan.get('component_metrics', {}), indent=2)}")

    # 6. Multiple queries to demonstrate statistics
    print("\n6. Running multiple queries to collect statistics...")

    for i in range(10):
        # Random vector query
        random_vector = np.random.rand(768).astype(np.float32)
        vector_optimizer.execute_vector_search(
            query_params={"query_vector": random_vector, "top_k": 10, "dimension": 768},
            search_func=optimized_search_func
        )

        # Random graph query
        entity_types = ["person", "organization", "location", "concept", "document"]
        rel_types = ["knows", "works_for", "located_in", "related_to", "mentions"]

        graph_optimizer.execute_graph_query(
            query_params={
                "query_type": "traverse",
                "start_entity_type": random.choice(entity_types),
                "relationship_types": random.sample(rel_types, k=min(2, len(rel_types))),
                "max_depth": random.randint(1, 3),
                "limit": 5
            },
            query_func=knowledge_graph.query
        )

    # 7. Get statistics and recommendations
    print("\n7. Query statistics and recommendations:")

    stats = base_optimizer.get_query_statistics()
    print("\nQuery Statistics:")
    print(json.dumps(stats, indent=2, default=str))

    recommendations = base_optimizer.get_optimization_recommendations()
    print("\nOptimization Recommendations:")
    print(json.dumps(recommendations, indent=2, default=str))

    print("\n=== Example Complete ===")


if __name__ == "__main__":
    run_example()
