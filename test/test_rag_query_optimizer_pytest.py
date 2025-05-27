"""
Advanced tests for the RAG Query Optimizer using pytest.

This module provides more advanced testing of the RAG Query Optimizer using pytest fixtures
and parametrized tests. It focuses on:
- Complex integration scenarios
- Parameter optimization and convergence
- Realistic query patterns from actual usage
- Performance under various load conditions
- Error handling and recovery mechanisms
"""

import pytest
import numpy as np
import time
import json
import os
import tempfile
import shutil
from typing import Dict, List, Any, Optional
from datetime import datetime, timedelta

# Components to test
from ipfs_datasets_py import (
    GraphRAGQueryStats,
    GraphRAGQueryOptimizer,
    QueryRewriter,
    QueryBudgetManager,
    UnifiedGraphRAGQueryOptimizer,
    QueryMetricsCollector,
    QueryVisualizer
)

# Mock classes and fixtures
class MockVectorStore:
    """Mock vector store for testing."""
    def __init__(self, latency=0.01, result_quality=0.9):
        self.latency = latency
        self.result_quality = result_quality
        self.call_count = 0
        
    def search(self, vector, top_k=5, min_score=0.0):
        self.call_count += 1
        # Simulate search latency
        time.sleep(self.latency)
        # Generate results with configurable quality
        return [
            {
                "id": f"vec_{i}", 
                "score": max(0.0, min(1.0, self.result_quality - (i * 0.05))), 
                "metadata": {"text": f"Vector result {i}"}, 
                "source": "vector"
            } 
            for i in range(top_k) 
            if (self.result_quality - (i * 0.05)) >= min_score
        ]

class MockGraphStore:
    """Mock graph store for testing."""
    def __init__(self, latency=0.02, branching_factor=3, result_quality=0.8):
        self.latency = latency
        self.branching_factor = branching_factor
        self.result_quality = result_quality
        self.call_count = 0
        
    def traverse_from_entities(self, entities: List[Dict], relationship_types: Optional[List[str]] = None, max_depth: int = 2):
        self.call_count += 1
        # Simulate traversal latency (increases with depth and entity count)
        time.sleep(self.latency * max_depth * (0.5 + 0.1 * len(entities)))
        
        results = []
        for i, entity_info in enumerate(entities):
            seed_id = entity_info.get("id", f"seed_{i}")
            # Simulate finding related entities with branching factor
            entities_added = 0
            for depth in range(max_depth):
                for branch in range(self.branching_factor):
                    if depth == 0 or (entities_added < (max_depth * self.branching_factor)):
                        score = max(0.0, min(1.0, self.result_quality - (depth * 0.1) - (branch * 0.05)))
                        results.append({
                            "id": f"{seed_id}_d{depth}_b{branch}", 
                            "properties": {"name": f"Related {depth}-{branch} to {seed_id}"},
                            "source": "graph", 
                            "score": score
                        })
                        entities_added += 1
        
        return results
        
class MockPerformanceMonitor:
    """Mock performance monitor for testing."""
    def __init__(self):
        self.metrics = {}
        
    def record_metric(self, name, value):
        if name not in self.metrics:
            self.metrics[name] = []
        self.metrics[name].append(value)
        
    def get_metrics(self, name):
        return self.metrics.get(name, [])
        
    def reset(self):
        self.metrics = {}

# Fixtures
@pytest.fixture
def temp_metrics_dir():
    """Create temporary directory for metrics storage."""
    metrics_dir = tempfile.mkdtemp()
    yield metrics_dir
    shutil.rmtree(metrics_dir)

@pytest.fixture
def metrics_collector(temp_metrics_dir):
    """Create a metrics collector for testing."""
    return QueryMetricsCollector(
        max_history_size=100,
        metrics_dir=temp_metrics_dir,
        track_resources=True
    )

@pytest.fixture
def unified_optimizer(metrics_collector):
    """Create a unified optimizer with metrics collector."""
    optimizer = UnifiedGraphRAGQueryOptimizer(
        metrics_collector=metrics_collector,
        metrics_dir=metrics_collector.metrics_dir
    )
    # Initialize with default statistical learning disabled
    return optimizer

@pytest.fixture
def statistically_enabled_optimizer(unified_optimizer):
    """Create optimizer with statistical learning enabled."""
    unified_optimizer.enable_statistical_learning(enabled=True, learning_cycle=5)
    return unified_optimizer

@pytest.fixture
def mock_vector_store():
    """Create a mock vector store."""
    return MockVectorStore()

@pytest.fixture
def mock_graph_store():
    """Create a mock graph store."""
    return MockGraphStore()

@pytest.fixture
def mock_monitor():
    """Create a mock performance monitor."""
    return MockPerformanceMonitor()

@pytest.fixture
def random_query_vector():
    """Generate a random query vector."""
    return np.random.rand(10)

@pytest.fixture
def query_variations():
    """Return a set of query variations for testing."""
    return [
        {
            "name": "basic_query",
            "query": {
                "query_text": "Basic test query",
                "max_vector_results": 5,
                "max_traversal_depth": 2
            }
        },
        {
            "name": "deep_traversal_query",
            "query": {
                "query_text": "Deep traversal query",
                "max_vector_results": 3,
                "max_traversal_depth": 5,
                "traversal": {"strategy": "depth_first"}
            }
        },
        {
            "name": "entity_lookup_query",
            "query": {
                "query_text": "Entity lookup query",
                "entity_id": "entity123",
                "skip_vector_search": True
            }
        },
        {
            "name": "fact_verification_query",
            "query": {
                "query_text": "Is entity A related to entity B?",
                "source_entity": "entityA",
                "target_entity": "entityB",
                "relation_type": "knows"
            }
        },
        {
            "name": "wikipedia_specific_query",
            "query": {
                "query_text": "What is the capital of France?",
                "graph_type": "wikipedia",
                "max_vector_results": 5,
                "max_traversal_depth": 2
            }
        }
    ]

# Basic functional tests with pytest
def test_optimizer_instantiation(unified_optimizer):
    """Test that the UnifiedGraphRAGQueryOptimizer is properly instantiated."""
    assert unified_optimizer is not None
    assert hasattr(unified_optimizer, 'query_stats')
    assert hasattr(unified_optimizer, 'rewriter')
    assert hasattr(unified_optimizer, 'budget_manager')

def test_enable_statistical_learning(unified_optimizer):
    """Test enabling statistical learning on the optimizer."""
    # Check default state
    assert getattr(unified_optimizer, '_learning_enabled', False) == False
    
    # Enable statistical learning
    unified_optimizer.enable_statistical_learning(enabled=True, learning_cycle=10)
    assert unified_optimizer._learning_enabled == True
    assert unified_optimizer._learning_cycle == 10
    
    # Set different cycle value
    unified_optimizer.enable_statistical_learning(enabled=True, learning_cycle=50)
    assert unified_optimizer._learning_cycle == 50
    
    # Disable statistical learning
    unified_optimizer.enable_statistical_learning(enabled=False)
    assert unified_optimizer._learning_enabled == False

# Parametrized tests for different query types
@pytest.mark.parametrize("query_type", [
    "basic_query", 
    "deep_traversal_query", 
    "entity_lookup_query", 
    "fact_verification_query", 
    "wikipedia_specific_query"
])
def test_optimize_query_variations(unified_optimizer, query_variations, random_query_vector, query_type):
    """Test optimizing different types of queries."""
    # Find the query by name
    query_info = next(q for q in query_variations if q["name"] == query_type)
    query = query_info["query"].copy()
    
    # Add query vector if not an entity-only query
    if not query.get("skip_vector_search") and not query.get("entity_id"):
        query["query_vector"] = random_query_vector
    
    # Run optimization
    plan = unified_optimizer.optimize_query(query)
    
    # Verify optimization produces valid plan
    assert plan is not None
    assert isinstance(plan, dict)
    assert "query" in plan
    
    # Type-specific checks
    if query_type == "entity_lookup_query":
        assert plan.get("query", {}).get("skip_vector_search") == True
    
    if query_type == "wikipedia_specific_query":
        assert plan.get("graph_type") == "wikipedia"

# Advanced statistical learning tests
def test_learning_from_mixed_query_patterns(statistically_enabled_optimizer, metrics_collector, random_query_vector, query_variations):
    """Test that statistical learning adapts to mixed query patterns."""
    # Define pattern frequencies (some patterns more common than others)
    pattern_frequencies = {
        "basic_query": 10,
        "deep_traversal_query": 5,
        "entity_lookup_query": 3,
        "fact_verification_query": 2,
        "wikipedia_specific_query": 5
    }
    
    # Generate queries according to frequency
    for pattern_name, frequency in pattern_frequencies.items():
        query_info = next(q for q in query_variations if q["name"] == pattern_name)
        base_query = query_info["query"].copy()
        
        for i in range(frequency):
            # Create variation of this query pattern
            query = base_query.copy()
            
            # Add query vector if needed
            if not query.get("skip_vector_search") and not query.get("entity_id"):
                query["query_vector"] = random_query_vector
            
            # Start tracking
            query_id = metrics_collector.start_query_tracking(query_params=query)
            
            # Simulate execution with different timing based on pattern
            if "deep_traversal" in pattern_name:
                # Deep traversals are slower
                with metrics_collector.time_phase("graph_traversal"):
                    time.sleep(0.1)
            elif "entity_lookup" in pattern_name:
                # Entity lookups are faster
                with metrics_collector.time_phase("entity_lookup"):
                    time.sleep(0.01)
            else:
                # Default timing
                with metrics_collector.time_phase("processing"):
                    time.sleep(0.05)
            
            # Simulate varying result qualities
            quality = 0.7 + (i % 3) * 0.1
            metrics_collector.end_query_tracking(
                results_count=5,
                quality_score=quality
            )
    
    # Learn from these patterns
    learning_results = statistically_enabled_optimizer._learn_from_query_statistics(
        recent_queries_count=25
    )
    
    # Verify learning results
    assert learning_results is not None
    assert learning_results["analyzed_queries"] > 0
    assert "optimization_rules" in learning_results
    assert len(learning_results["optimization_rules"]) > 0
    
    # Now optimize a query and verify rules applied
    basic_query = next(q for q in query_variations if q["name"] == "basic_query")["query"].copy()
    basic_query["query_vector"] = random_query_vector
    
    plan = statistically_enabled_optimizer.optimize_query(basic_query)
    assert plan is not None

# Integration test with mock stores
def test_end_to_end_optimization_execution(
    statistically_enabled_optimizer, 
    mock_vector_store, 
    mock_graph_store, 
    random_query_vector
):
    """Test end-to-end optimization and execution with mock stores."""
    # Create a query
    query = {
        "query_vector": random_query_vector,
        "query_text": "Test query for end-to-end flow",
        "max_vector_results": 5,
        "max_traversal_depth": 2
    }
    
    # Set up a tracking method to see if stores are accessed correctly
    vector_called = False
    graph_called = False
    
    def vector_search_func(vector, params):
        nonlocal vector_called
        vector_called = True
        top_k = params.get("max_vector_results", 5)
        return mock_vector_store.search(vector, top_k=top_k)
    
    def graph_traversal_func(entities, params):
        nonlocal graph_called
        graph_called = True
        max_depth = params.get("max_traversal_depth", 2)
        return mock_graph_store.traverse_from_entities(entities, max_depth=max_depth)
    
    # Execute the optimized query
    statistically_enabled_optimizer.execute_optimized_query(
        query=query,
        vector_search_func=vector_search_func,
        graph_traversal_func=graph_traversal_func
    )
    
    # Verify stores were called
    assert vector_called == True
    assert graph_called == True

# Test JSON serialization with NumPy arrays
def test_json_serialization_with_numpy(metrics_collector, temp_metrics_dir):
    """Test that JSON serialization correctly handles NumPy arrays."""
    try:
        import numpy as np
        
        # Create metrics with NumPy values
        metrics = {
            "query_id": "numpy_test",
            "start_time": time.time(),
            "end_time": time.time() + 1.0,
            "duration": 1.0,
            "phases": {
                "test_phase": {
                    "duration": 0.5,
                    "count": 1
                }
            },
            "params": {},
            "results": {
                "count": 10,
                "quality_score": 0.85
            },
            "resources": {
                "peak_memory": 1024 * 1024
            },
            # Add NumPy values
            "numpy_array": np.array([1, 2, 3, 4, 5]),
            "numpy_scalar": np.float32(3.14),
            "numpy_int": np.int64(42),
            "numpy_bool": np.bool_(True),
            "nested": {
                "numpy_value": np.float64(2.718)
            },
            "statistics": {
                "std_dev": np.std([1, 2, 3, 4, 5])
            }
        }
        
        # Call persist_metrics directly
        metrics_collector._persist_metrics(metrics)
        
        # Check if file was created
        files = [f for f in os.listdir(temp_metrics_dir) if "numpy_test" in f]
        assert len(files) == 1, "Should have created one metrics file"
        
        # Read the file and parse JSON
        filepath = os.path.join(temp_metrics_dir, files[0])
        with open(filepath, 'r') as f:
            parsed_metrics = json.load(f)
        
        # Check if NumPy array was converted to list
        assert isinstance(parsed_metrics["numpy_array"], list), "NumPy array should be converted to list"
        assert parsed_metrics["numpy_array"] == [1, 2, 3, 4, 5]
        
        # Check if NumPy scalar was converted to Python type
        assert isinstance(parsed_metrics["numpy_scalar"], float), "NumPy scalar should be converted to float"
        assert abs(parsed_metrics["numpy_scalar"] - 3.14) < 0.001
        
        # Check if NumPy int was converted to Python int
        assert isinstance(parsed_metrics["numpy_int"], int), "NumPy int should be converted to int"
        assert parsed_metrics["numpy_int"] == 42
        
        # Check if NumPy bool was converted to Python bool
        assert isinstance(parsed_metrics["numpy_bool"], bool), "NumPy bool should be converted to bool"
        assert parsed_metrics["numpy_bool"] == True
        
        # Check nested NumPy value
        assert isinstance(parsed_metrics["nested"]["numpy_value"], float)
        assert abs(parsed_metrics["nested"]["numpy_value"] - 2.718) < 0.001
        
        # Check calculated statistics
        assert isinstance(parsed_metrics["statistics"]["std_dev"], float)
        
        # Test export_metrics_json
        metrics_collector.query_metrics.append(metrics)
        json_file = os.path.join(temp_metrics_dir, "metrics_export.json")
        metrics_collector.export_metrics_json(json_file)
        
        # Check if file was created
        assert os.path.exists(json_file), "JSON export file should exist"
        
        # Read and parse the file
        with open(json_file, 'r') as f:
            exported_data = json.load(f)
        
        # Verify content
        assert len(exported_data) > 0, "Should have exported metrics"
        
    except ImportError:
        pytest.skip("NumPy not available")

# Performance testing
@pytest.mark.parametrize("num_queries", [10, 50])
def test_optimization_performance(unified_optimizer, random_query_vector, num_queries):
    """Test optimization performance with different query volumes."""
    query = {
        "query_vector": random_query_vector,
        "query_text": "Performance test query",
        "max_vector_results": 5,
        "max_traversal_depth": 2
    }
    
    # Record timing
    start_time = time.time()
    
    # Process multiple queries
    for i in range(num_queries):
        plan = unified_optimizer.optimize_query(query)
        assert plan is not None
    
    execution_time = time.time() - start_time
    
    # Performance assertion - this is volume-dependent but should be reasonable
    # For 50 queries should take less than 5 seconds on typical hardware
    assert execution_time < (num_queries * 0.1)

# Error handling testing
def test_error_handling_during_query_optimization(unified_optimizer, random_query_vector):
    """Test error handling during query optimization."""
    # Create invalid query (missing key components)
    invalid_query = {
        # No query_vector
        "max_vector_results": -1,  # Invalid value
        "max_traversal_depth": "invalid"  # Wrong type
    }
    
    # Should not raise exception but return fallback plan
    plan = unified_optimizer.optimize_query(invalid_query)
    assert plan is not None
    assert "query" in plan
    
    # Try with partially valid query
    partial_query = {
        "query_vector": random_query_vector,
        "invalid_parameter": "test"
    }
    
    plan = unified_optimizer.optimize_query(partial_query)
    assert plan is not None
    assert "query" in plan

# Persistence testing
def test_metrics_persistence(metrics_collector, temp_metrics_dir):
    """Test persistence of metrics to disk."""
    # Record some metrics
    for i in range(5):
        query_id = metrics_collector.start_query_tracking(
            query_params={"test_param": i}
        )
        with metrics_collector.time_phase("processing"):
            time.sleep(0.01)
        metrics_collector.end_query_tracking(results_count=i)
    
    # Force save
    metrics_collector.save_metrics()
    
    # Check for files
    metrics_files = [f for f in os.listdir(temp_metrics_dir) if f.endswith('.json')]
    assert len(metrics_files) > 0
    
    # Load one file and check contents
    with open(os.path.join(temp_metrics_dir, metrics_files[0]), 'r') as f:
        data = json.load(f)
        assert isinstance(data, dict)
        assert "metrics" in data or "queries" in data

# Statistical learning parameter adaptation test
def test_parameter_adaptation(statistically_enabled_optimizer, metrics_collector):
    """Test that parameters adapt based on query performance."""
    # Record initial parameters
    if hasattr(statistically_enabled_optimizer, '_default_max_depth'):
        initial_max_depth = statistically_enabled_optimizer._default_max_depth
    else:
        initial_max_depth = 2  # Assume default
        
    # Train on queries that perform best with specific parameters
    optimal_depth = 4
    
    # Generate metrics showing good performance with the optimal depth
    for i in range(15):
        query_id = metrics_collector.start_query_tracking(
            query_params={
                "traversal": {"max_depth": optimal_depth},
                "vector_params": {"top_k": 5}
            }
        )
        
        # Fast execution time
        with metrics_collector.time_phase("processing"):
            time.sleep(0.01)
            
        # High quality results
        metrics_collector.end_query_tracking(
            results_count=10,
            quality_score=0.9
        )
    
    # For comparison, add some queries with suboptimal parameters
    for i in range(5):
        query_id = metrics_collector.start_query_tracking(
            query_params={
                "traversal": {"max_depth": 2},  # Suboptimal
                "vector_params": {"top_k": 5}
            }
        )
        
        # Slower execution
        with metrics_collector.time_phase("processing"):
            time.sleep(0.05)
            
        # Lower quality
        metrics_collector.end_query_tracking(
            results_count=3,
            quality_score=0.6
        )
    
    # Force learning
    learning_results = statistically_enabled_optimizer._learn_from_query_statistics(recent_queries_count=20)
    assert learning_results is not None
    
    # Check optimization rules
    optimization_rules = learning_results.get("optimization_rules", [])
    assert len(optimization_rules) > 0
    
    # Verify adaptation of max_depth default parameter, if field exists
    if hasattr(statistically_enabled_optimizer, '_default_max_depth'):
        assert statistically_enabled_optimizer._default_max_depth is not None
