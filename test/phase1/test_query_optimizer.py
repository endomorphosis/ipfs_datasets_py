import os
import sys
import unittest
import time
import tempfile
import numpy as np
import random
from typing import Dict, List, Any, Tuple, Optional

# Add parent directory to path to import the module
parent_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
sys.path.append(parent_dir)

# Import the module to test
from ipfs_datasets_py.query_optimizer import (
    QueryOptimizer, QueryStatsCollector, LRUQueryCache, IndexRegistry,
    VectorIndexOptimizer, KnowledgeGraphQueryOptimizer, HybridQueryOptimizer,
    create_query_optimizer, QueryMetrics
)


class MockVectorIndex:
    """Mock vector index for testing."""
    
    def __init__(self, dimension=128, size=1000):
        """Initialize with random vectors."""
        self.dimension = dimension
        self.vectors = np.random.rand(size, dimension).astype(np.float32)
        self.metadata = [{"id": i, "label": f"Vector {i}"} for i in range(size)]
    
    def search(self, query_params):
        """Simulate a vector search."""
        query_vector = query_params.get("query_vector")
        if query_vector is None:
            query_vector = np.random.rand(self.dimension).astype(np.float32)
        
        top_k = query_params.get("top_k", 10)
        
        # Simulate some processing time based on parameters
        ef_search = query_params.get("ef_search", 100)
        exact_search = query_params.get("exact_search", False)
        
        # Slower for exact search or high ef_search
        time.sleep(0.001 * (1 + (0.5 if exact_search else 0) + (ef_search / 100)))
        
        # Compute mock results (just random indices and scores)
        indices = np.random.choice(len(self.vectors), min(top_k, len(self.vectors)), replace=False)
        scores = np.random.rand(len(indices))
        
        # Sort by score
        sorted_idx = np.argsort(-scores)
        indices = indices[sorted_idx]
        scores = scores[sorted_idx]
        
        # Create result objects
        results = []
        for i, score in zip(indices, scores):
            results.append({
                "id": i,
                "score": float(score),
                "metadata": self.metadata[i]
            })
        
        # Add scan count attribute
        results.scan_count = len(self.vectors) // (5 if not exact_search else 1)
        
        return results


class MockKnowledgeGraph:
    """Mock knowledge graph for testing."""
    
    def __init__(self, num_entities=100, num_relationships=300):
        """Initialize with random entities and relationships."""
        self.entities = []
        self.relationships = []
        entity_types = ["person", "organization", "location", "event", "concept"]
        
        # Create entities
        for i in range(num_entities):
            entity_type = random.choice(entity_types)
            self.entities.append({
                "id": f"entity_{i}",
                "type": entity_type,
                "properties": {
                    "name": f"{entity_type.capitalize()} {i}",
                    "created_at": time.time()
                }
            })
        
        # Create relationships
        relationship_types = ["knows", "works_for", "located_in", "participated_in", "related_to"]
        for i in range(num_relationships):
            rel_type = random.choice(relationship_types)
            source_idx = random.randint(0, num_entities - 1)
            target_idx = random.randint(0, num_entities - 1)
            
            self.relationships.append({
                "id": f"rel_{i}",
                "type": rel_type,
                "source": self.entities[source_idx]["id"],
                "target": self.entities[target_idx]["id"],
                "properties": {
                    "created_at": time.time()
                }
            })
    
    def traverse(self, query_params):
        """Simulate a graph traversal."""
        start_entity_type = query_params.get("start_entity_type")
        relationship_types = query_params.get("relationship_types", [])
        max_depth = query_params.get("max_depth", 1)
        
        # Filter starting entities by type if specified
        if start_entity_type:
            start_entities = [e for e in self.entities if e["type"] == start_entity_type]
        else:
            start_entities = self.entities
        
        # Simulate traversal time based on parameters
        path_plan = query_params.get("path_plan", [])
        traversal_cost = sum(step.get("estimated_cost", 1.0) for step in path_plan) if path_plan else max_depth
        time.sleep(0.001 * traversal_cost)
        
        # Generate mock results
        results = []
        for _ in range(min(10, len(start_entities))):
            entity = random.choice(start_entities)
            path = [entity]
            
            # Add random path of relationships and entities
            current_entity = entity
            for _ in range(random.randint(0, max_depth)):
                # Find outgoing relationships
                outgoing = [r for r in self.relationships 
                           if r["source"] == current_entity["id"]
                           and (not relationship_types or r["type"] in relationship_types)]
                
                if not outgoing:
                    break
                    
                # Choose a random relationship
                rel = random.choice(outgoing)
                path.append(rel)
                
                # Find target entity
                target_entity = next((e for e in self.entities if e["id"] == rel["target"]), None)
                if target_entity:
                    path.append(target_entity)
                    current_entity = target_entity
            
            results.append({
                "start_entity": entity,
                "path": path,
                "path_length": len(path)
            })
        
        # Add scan count attribute
        results.scan_count = len(start_entities) * traversal_cost
        
        return results


def merge_vector_graph_results(vector_results, graph_results, vector_weight, graph_weight):
    """Merge vector and graph results for testing."""
    # Simple mock implementation that just combines the results
    merged = []
    
    # Add vector results
    for i, result in enumerate(vector_results):
        merged.append({
            "id": f"v_{result['id']}",
            "source": "vector",
            "score": result["score"] * vector_weight,
            "original_result": result
        })
    
    # Add graph results
    for i, result in enumerate(graph_results):
        merged.append({
            "id": f"g_{result['start_entity']['id']}",
            "source": "graph",
            "score": (1.0 - (i / len(graph_results))) * graph_weight,
            "original_result": result
        })
    
    # Sort by score
    merged.sort(key=lambda x: x["score"], reverse=True)
    
    return merged[:10]  # Return top 10


class TestQueryOptimizer(unittest.TestCase):
    def setUp(self):
        """Set up test fixtures before each test."""
        self.stats_collector = QueryStatsCollector()
        self.query_cache = LRUQueryCache()
        self.index_registry = IndexRegistry()
        
        self.query_optimizer = QueryOptimizer(
            stats_collector=self.stats_collector,
            query_cache=self.query_cache,
            index_registry=self.index_registry
        )
        
        # Create mock indexes
        self.index_registry.register_index(
            name="vector_index_128",
            index_type="vector",
            fields=["vector"],
            metadata={"dimension": 128}
        )
        
        self.index_registry.register_index(
            name="entity_type_index",
            index_type="graph",
            fields=["type"]
        )
        
        # Create mock data sources
        self.vector_index = MockVectorIndex(dimension=128, size=1000)
        self.knowledge_graph = MockKnowledgeGraph(num_entities=100, num_relationships=300)
        
        # Create specialized optimizers
        self.vector_optimizer = VectorIndexOptimizer(self.query_optimizer)
        self.graph_optimizer = KnowledgeGraphQueryOptimizer(self.query_optimizer)
        self.hybrid_optimizer = HybridQueryOptimizer(self.vector_optimizer, self.graph_optimizer)
    
    def test_basic_query_optimization(self):
        """Test basic query optimization and execution."""
        # Define a test query
        query_params = {
            "query_vector": np.random.rand(128).astype(np.float32),
            "top_k": 10,
            "dimension": 128
        }
        
        # Optimize the query
        query_plan = self.query_optimizer.optimize_query("vector_search", query_params)
        
        # Verify the plan contains expected information
        self.assertEqual(query_plan["query_type"], "vector_search")
        self.assertIn("query_id", query_plan)
        self.assertIn("optimized_params", query_plan)
        
        # Execute the query
        result, metrics = self.query_optimizer.execute_query(
            query_type="vector_search",
            query_params=query_params,
            query_func=self.vector_index.search
        )
        
        # Verify result and metrics
        self.assertTrue(isinstance(result, list))
        self.assertEqual(metrics.query_type, "vector_search")
        self.assertFalse(metrics.cache_hit)
        self.assertGreater(metrics.duration_ms, 0)
        
        # Execute again to test caching
        result2, metrics2 = self.query_optimizer.execute_query(
            query_type="vector_search",
            query_params=query_params,
            query_func=self.vector_index.search
        )
        
        # Verify cache hit
        self.assertTrue(metrics2.cache_hit)
        self.assertEqual(metrics2.scan_count, 0)
        
        # Verify that first and second results are identical
        self.assertEqual(len(result), len(result2))
    
    def test_vector_index_optimization(self):
        """Test vector index specific optimizations."""
        # Define a test query
        query_params = {
            "query_vector": np.random.rand(128).astype(np.float32),
            "top_k": 10,
            "dimension": 128
        }
        
        # Optimize the query using the vector optimizer
        vector_plan = self.vector_optimizer.optimize_vector_search(query_params)
        
        # Verify the plan has vector-specific optimizations
        self.assertIn("vector_specific", vector_plan)
        self.assertEqual(vector_plan["vector_specific"]["dimension"], 128)
        self.assertIn("exact_search", vector_plan["vector_specific"])
        self.assertIn("ef_search", vector_plan["vector_specific"])
        
        # Execute the optimized query
        result, metrics = self.vector_optimizer.execute_vector_search(
            query_params=query_params,
            search_func=self.vector_index.search
        )
        
        # Verify result and metrics
        self.assertTrue(isinstance(result, list))
        self.assertEqual(metrics.query_type, "vector_search")
        self.assertGreater(metrics.duration_ms, 0)
        
        # Tune vector parameters and verify changes
        perf_metrics = {
            "avg_search_time_ms": 5.0,
            "avg_accuracy": 0.92
        }
        tuned_params = self.vector_optimizer.tune_vector_index_params(128, perf_metrics)
        
        self.assertEqual(tuned_params["dimension"], 128)
        self.assertIn("ef_search", tuned_params)
    
    def test_graph_query_optimization(self):
        """Test knowledge graph query optimization."""
        # Define a test query
        query_params = {
            "start_entity_type": "person",
            "relationship_types": ["knows", "works_for"],
            "max_depth": 2
        }
        
        # Optimize the query using the graph optimizer
        graph_plan = self.graph_optimizer.optimize_graph_query(query_params)
        
        # Verify the plan has graph-specific optimizations
        self.assertIn("graph_specific", graph_plan)
        self.assertEqual(graph_plan["graph_specific"]["start_entity_type"], "person")
        self.assertIn("path_plan", graph_plan["graph_specific"])
        
        # Execute the optimized query
        result, metrics = self.graph_optimizer.execute_graph_query(
            query_params=query_params,
            query_func=self.knowledge_graph.traverse
        )
        
        # Verify result and metrics
        self.assertTrue(isinstance(result, list))
        self.assertEqual(metrics.query_type, "graph_traversal")
        self.assertGreater(metrics.duration_ms, 0)
        
        # Test pattern caching
        result2, metrics2 = self.graph_optimizer.execute_graph_query(
            query_params=query_params,
            query_func=self.knowledge_graph.traverse
        )
        
        # Verify pattern cache hit
        self.assertTrue(metrics2.cache_hit)
        self.assertEqual(metrics2.scan_count, 0)
        
        # Update relationship costs and verify changes
        self.graph_optimizer.update_relationship_costs({
            "knows": 0.5,
            "works_for": 1.5
        })
        
        # Test with updated costs
        graph_plan2 = self.graph_optimizer.optimize_graph_query(query_params)
        # Costs are reflected in the path plan
        path_plan = graph_plan2["graph_specific"]["path_plan"]
        self.assertTrue(any(step["estimated_cost"] == 2.0 for step in path_plan))
    
    def test_hybrid_query_optimization(self):
        """Test hybrid query optimization."""
        # Define a test query
        query_params = {
            "vector_component": {
                "query_vector": np.random.rand(128).astype(np.float32),
                "top_k": 10,
                "dimension": 128
            },
            "graph_component": {
                "start_entity_type": "person",
                "relationship_types": ["knows", "works_for"],
                "max_depth": 2
            },
            "vector_weight": 0.7,
            "graph_weight": 0.3
        }
        
        # Optimize the query using the hybrid optimizer
        hybrid_plan = self.hybrid_optimizer.optimize_hybrid_query(query_params)
        
        # Verify the plan has hybrid-specific optimizations
        self.assertEqual(hybrid_plan["query_type"], "hybrid_search")
        self.assertIn("optimized_params", hybrid_plan)
        self.assertIn("component_plans", hybrid_plan)
        self.assertIn("adaptive_weights", hybrid_plan)
        
        # Execute the optimized query
        result, metrics = self.hybrid_optimizer.execute_hybrid_query(
            query_params=query_params,
            vector_func=self.vector_index.search,
            graph_func=self.knowledge_graph.traverse,
            merge_func=merge_vector_graph_results
        )
        
        # Verify result and metrics
        self.assertTrue(isinstance(result, list))
        self.assertEqual(metrics.query_type, "hybrid_search")
        self.assertGreater(metrics.duration_ms, 0)
        
        # Verify result contents
        self.assertTrue(any(r["source"] == "vector" for r in result))
        self.assertTrue(any(r["source"] == "graph" for r in result))
    
    def test_query_stats_collection(self):
        """Test query statistics collection and analysis."""
        # Execute a few different queries
        for _ in range(5):
            self.query_optimizer.execute_query(
                query_type="vector_search",
                query_params={"query_vector": np.random.rand(128), "top_k": 10, "dimension": 128},
                query_func=self.vector_index.search
            )
        
        for _ in range(3):
            self.query_optimizer.execute_query(
                query_type="graph_traversal",
                query_params={"start_entity_type": "person", "max_depth": 2},
                query_func=self.knowledge_graph.traverse
            )
        
        # Get statistics
        stats = self.query_optimizer.get_query_statistics()
        
        # Verify statistics
        self.assertEqual(stats["total_queries"], 8)
        self.assertEqual(stats["query_type_distribution"]["vector_search"], 5)
        self.assertEqual(stats["query_type_distribution"]["graph_traversal"], 3)
        
        # Check recommendations
        recommendations = self.query_optimizer.get_optimization_recommendations()
        self.assertTrue(isinstance(recommendations, list))
    
    def test_lru_cache(self):
        """Test LRU cache functionality."""
        cache = LRUQueryCache(max_size=2)
        
        # Add two items
        cache.put("query1", {"param": "value1"}, "result1")
        cache.put("query2", {"param": "value2"}, "result2")
        
        # Verify both are in cache
        hit1, result1 = cache.get("query1", {"param": "value1"})
        hit2, result2 = cache.get("query2", {"param": "value2"})
        
        self.assertTrue(hit1)
        self.assertTrue(hit2)
        self.assertEqual(result1, "result1")
        self.assertEqual(result2, "result2")
        
        # Add third item, should evict first
        cache.put("query3", {"param": "value3"}, "result3")
        
        # Verify first item is evicted
        hit1, _ = cache.get("query1", {"param": "value1"})
        hit3, result3 = cache.get("query3", {"param": "value3"})
        
        self.assertFalse(hit1)
        self.assertTrue(hit3)
        self.assertEqual(result3, "result3")
        
        # Invalidate specific query type
        cache.invalidate("query2")
        hit2, _ = cache.get("query2", {"param": "value2"})
        self.assertFalse(hit2)
        
        # Verify size
        self.assertEqual(cache.size(), 1)
    
    def test_index_registry(self):
        """Test index registry functionality."""
        registry = IndexRegistry()
        
        # Register indexes
        registry.register_index(
            name="test_index_1",
            index_type="btree",
            fields=["name", "age"],
            metadata={"unique": True}
        )
        
        registry.register_index(
            name="test_index_2",
            index_type="hash",
            fields=["id"],
            metadata={"unique": True}
        )
        
        # Get index
        index1 = registry.get_index("test_index_1")
        self.assertEqual(index1["name"], "test_index_1")
        self.assertEqual(index1["type"], "btree")
        self.assertEqual(index1["fields"], ["name", "age"])
        
        # Find indexes for fields
        indexes = registry.find_indexes_for_fields(["name"])
        self.assertEqual(len(indexes), 1)
        self.assertEqual(indexes[0]["name"], "test_index_1")
        
        # Unregister index
        result = registry.unregister_index("test_index_1")
        self.assertTrue(result)
        
        # Verify it's gone
        self.assertIsNone(registry.get_index("test_index_1"))
        
        # Get all indexes
        all_indexes = registry.get_all_indexes()
        self.assertEqual(len(all_indexes), 1)
        self.assertEqual(all_indexes[0]["name"], "test_index_2")
    
    def test_factory_function(self):
        """Test the optimizer factory function."""
        # Create optimizers using factory
        optimizers = create_query_optimizer(
            max_cache_size=50,
            collect_statistics=True,
            optimize_vectors=True,
            optimize_graphs=True,
            optimize_hybrid=True
        )
        
        # Verify all components are created
        self.assertIn("base", optimizers)
        self.assertIn("vector", optimizers)
        self.assertIn("graph", optimizers)
        self.assertIn("hybrid", optimizers)
        
        # Verify they're working
        base_optimizer = optimizers["base"]
        vector_optimizer = optimizers["vector"]
        
        # Test basic optimization
        query_params = {
            "query_vector": np.random.rand(128).astype(np.float32),
            "top_k": 5,
            "dimension": 128
        }
        
        plan = vector_optimizer.optimize_vector_search(query_params)
        self.assertIn("vector_specific", plan)


if __name__ == "__main__":
    unittest.main()