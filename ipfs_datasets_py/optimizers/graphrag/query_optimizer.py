"""
Query Optimization Module for GraphRAG operations.

This module provides a comprehensive framework for optimizing GraphRAG (Graph Retrieval
Augmented Generation) queries across different knowledge graph types. The optimization
strategies are tailored to the specific characteristics of Wikipedia-derived knowledge
graphs, IPLD-based knowledge graphs, and mixed environments containing both types.

Key features:
- Query statistics collection and analysis for adaptive optimization
- Intelligent caching of frequently executed queries
- Query plan generation and execution with content-type awareness
- Vector index partitioning for improved search performance across large datasets
- Specialized optimizations for Wikipedia-derived knowledge graphs
- IPLD-specific optimizations leveraging content-addressed data structures
- Cross-document reasoning query planning with entity-based traversal
- Content-addressed graph traversal strategies for IPLD DAGs
- Multi-graph query optimization for mixed environments
- Performance analysis and recommendations
- Adaptive parameter tuning based on query patterns
- Query rewriting for improved traversal paths
- Advanced caching mechanisms for frequently accessed paths
- Hierarchical traversal planning with hop-limited paths
- Query cost estimation and budget-aware execution
- Enhanced metrics collection and visualization for query performance analysis
- Resource utilization tracking and bottleneck identification
- Query execution plan visualization with detailed timing breakdowns
- Historical performance analysis for optimization suggestions
- Interactive dashboard support with exportable metrics

Advanced Optimization Components:
- QueryRewriter: Analyzes and rewrites queries for better performance using:
  - Predicate pushdown for early filtering
  - Join reordering based on edge selectivity
  - Traversal path optimization based on graph characteristics
  - Pattern-specific optimizations for common query types
  - Domain-specific query transformations

- QueryBudgetManager: Manages query execution resources through:
  - Dynamic resource allocation based on query priority and complexity
  - Early stopping based on result quality and diminishing returns
  - Adaptive computation budgeting based on query history
  - Progressive query expansion driven by initial results
  - Timeout management and cost estimation

- UnifiedGraphRAGQueryOptimizer: Combines optimization strategies for different graph types:
  - Auto-detection of graph type from query parameters
  - Wikipedia-specific and IPLD-specific optimizations
  - Cross-graph query planning for heterogeneous environments
  - Comprehensive performance analysis and recommendation generation
  - Integration with advanced rewriting and budget management

- QueryMetricsCollector: Gathers detailed metrics on query execution:
  - Fine-grained timing measurements for each query phase
  - Resource utilization tracking (memory, computation)
  - Query plan effectiveness scoring
  - Pattern recognition across query executions
  - Integration with monitoring systems

- QueryVisualizer: Provides visualization capabilities for query analysis:
  - Query execution plan visual representation
  - Performance breakdown charts and timelines
  - Comparative analysis between query strategies
  - Graph traversal pattern visualization
  - Optimization opportunity highlighting

This module integrates with the llm_graphrag module to provide optimized graph
traversal strategies that enhance cross-document reasoning capabilities with LLMs.
"""

from __future__ import annotations

import logging
import time
import hashlib
import json
import re
import os
import csv
import uuid
import datetime

from ipfs_datasets_py.optimizers.graphrag.learning_adapter import (
    apply_learning_hook,
    check_learning_cycle,
    increment_failure_counter,
)
from ipfs_datasets_py.optimizers.graphrag.query_metrics import QueryMetricsCollector

# Optional dependencies with graceful fallbacks
try:
    import numpy as np
    HAVE_NUMPY = True
except ImportError:
    HAVE_NUMPY = False
    # Provide minimal numpy-like functionality for basic operations
    class MockNumpy:
        @staticmethod
        def array(x):
            return list(x) if hasattr(x, '__iter__') else [x]
        @staticmethod
        def mean(x):
            return sum(x) / len(x) if x else 0
        @staticmethod
        def std(x):
            if not x:
                return 0
            mean_val = sum(x) / len(x)
            variance = sum((val - mean_val) ** 2 for val in x) / len(x)
            return variance ** 0.5
    np = MockNumpy()

try:
    import psutil
    HAVE_PSUTIL = True
except ImportError:
    HAVE_PSUTIL = False
    # Mock psutil for basic functionality
    class MockPsutil:
        @staticmethod
        def virtual_memory():
            return type('Memory', (), {'percent': 50, 'available': 1000000000})()
        @staticmethod
        def cpu_percent():
            return 25.0

        class Process:
            def memory_info(self):
                return type('MemInfo', (), {'rss': 0, 'vms': 0})()

            def cpu_percent(self):
                return 0.0

    psutil = MockPsutil()
import copy
import math
from io import StringIO
from typing import Dict, List, Any, Optional, Tuple, Callable, Union, Set, TYPE_CHECKING, Iterator
from collections import defaultdict, OrderedDict, deque
from contextlib import contextmanager

# Optional visualization dependencies
if TYPE_CHECKING:
    from matplotlib.figure import Figure
    from matplotlib.axes import Axes
else:
    class Figure:  # pragma: no cover
        pass

    class Axes:  # pragma: no cover
        pass

try:
    import matplotlib.pyplot as plt
    import matplotlib.colors as mcolors
    import networkx as nx
    VISUALIZATION_AVAILABLE = True
except ImportError:
    VISUALIZATION_AVAILABLE = False
    # Create dummy Figure type for type annotations
    Figure = Any

# Import for Wikipedia-specific optimizations
# Import necessary components (optional: pulls in heavier ML deps)
try:
    from ipfs_datasets_py.ml.llm.llm_reasoning_tracer import WikipediaKnowledgeGraphTracer
    from ipfs_datasets_py.ml.llm.llm_graphrag import GraphRAGLLMProcessor
    LLM_GRAPHRAG_AVAILABLE = True
except ImportError:
    WikipediaKnowledgeGraphTracer = None  # type: ignore[assignment]
    GraphRAGLLMProcessor = None  # type: ignore[assignment]
    LLM_GRAPHRAG_AVAILABLE = False

# Import for Wikipedia-specific optimizations
try:
    from ipfs_datasets_py.optimizers.graphrag.wikipedia_optimizer import (
        detect_graph_type,
        create_appropriate_optimizer,
        optimize_wikipedia_query,
        UnifiedWikipediaGraphRAGQueryOptimizer
    )
    WIKIPEDIA_OPTIMIZER_AVAILABLE = True
except ImportError:
    WIKIPEDIA_OPTIMIZER_AVAILABLE = False

# Avoid circular imports with conditional imports
if TYPE_CHECKING:
    # from ipfs_datasets_py.ml.llm.llm_graphrag import GraphRAGLLMProcessor, ReasoningEnhancer # Keep commented if not strictly needed for type hints here
    pass

from ipfs_datasets_py.optimizers.graphrag.query_stats import GraphRAGQueryStats
from ipfs_datasets_py.optimizers.graphrag.query_planner import GraphRAGQueryOptimizer


from ipfs_datasets_py.optimizers.graphrag.query_rewriter import QueryRewriter
from ipfs_datasets_py.optimizers.graphrag.query_budget import QueryBudgetManager
from ipfs_datasets_py.optimizers.graphrag.query_visualizer import QueryVisualizer

from ipfs_datasets_py.optimizers.graphrag.query_unified_optimizer import UnifiedGraphRAGQueryOptimizer

def example_usage():
    """Example usage of the RAG Query Optimizer components."""
    # Sample query vector (would come from an embedding model in real usage)
    query_vector = np.random.rand(768)
    
    # Initialize components
    stats = GraphRAGQueryStats()
    optimizer = GraphRAGQueryOptimizer(query_stats=stats)
    query_rewriter = QueryRewriter()
    budget_manager = QueryBudgetManager()
    
    # Create the unified optimizer
    unified_optimizer = UnifiedGraphRAGQueryOptimizer(
        rewriter=query_rewriter,
        budget_manager=budget_manager,
        base_optimizer=optimizer,
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

    # Instantiate the LLM Processor, passing the unified optimizer to it
    # In a real scenario, llm_interface and prompt_library might be configured
    try:
        llm_processor = GraphRAGLLMProcessor(query_optimizer=unified_optimizer)
        print("Successfully instantiated GraphRAGLLMProcessor with UnifiedGraphRAGQueryOptimizer.")
    except Exception as e:
        print(f"Error instantiating GraphRAGLLMProcessor: {e}")
        # Continue with other parts of the example if possible
        llm_processor = None

    # Create a sample query (can still be used for planning/analysis)
    query = {
        "query_vector": query_vector,
        "max_vector_results": 10,
        "max_traversal_depth": 3,
        "edge_types": ["instance_of", "part_of", "created_by"],
        "min_similarity": 0.6,
        "query_text": "What is the relationship between quantum mechanics and general relativity?"
    }
    
    # Get a detailed execution plan
    plan = unified_optimizer.get_execution_plan(query, priority="high")
    print(f"Execution Plan: {json.dumps(plan, indent=2)}")

    # --- Removed MockGraphRAGProcessor and execute_query call ---
    # The actual execution would now happen via methods on the llm_processor instance,
    # which internally uses the unified_optimizer.
    # Example call (conceptual, requires actual data for documents/connections):
    if llm_processor:
        print("\n--- Conceptual Call to synthesize_cross_document_reasoning ---")
        # Define mock documents and connections for demonstration
        mock_documents = [
            {"id": "doc1", "title": "Paper A", "content": "Content about topic X."},
            {"id": "doc2", "title": "Paper B", "content": "More content about topic X and Y."}
        ]
        mock_connections = [ # This structure might differ based on actual implementation
             {"doc1": mock_documents[0], "doc2": mock_documents[1], "entity": {"id": "entity1", "name": "Topic X"}, "connection_type": "discusses"}
        ]
        mock_connections_text = llm_processor._format_connections_for_llm(mock_connections, "moderate") # Use internal helper for example

        try:
            reasoning_result = llm_processor.synthesize_cross_document_reasoning(
                query=query.get("query_text", ""),
                documents=mock_documents,
                connections=mock_connections_text, # Pass formatted text
                reasoning_depth="moderate",
                graph_info=unified_optimizer.graph_info,
                query_vector=query_vector
            )
            # Note: The actual LLM call is likely mocked or requires setup.
            # This primarily demonstrates the flow of calling the method.
            print(f"Reasoning Result (conceptual/mocked): {json.dumps(reasoning_result, indent=2, default=str)}")
        except Exception as e:
            print(f"Error during conceptual call to synthesize_cross_document_reasoning: {e}")
            print("Note: This might be expected if LLM interface is not configured.")
        print("--- End Conceptual Call ---")

    # Analyze performance
    performance_analysis = unified_optimizer.analyze_performance()
    print(f"Performance Analysis: {json.dumps(performance_analysis, indent=2)}")
    
    # Example of using visualization methods (if visualization is available)
    if VISUALIZATION_AVAILABLE and hasattr(unified_optimizer, "visualizer") and unified_optimizer.visualizer:
        print("\nVisualizations:")
        # Note: In a real application, you might want to check if last_query_id is set before visualizing
        if hasattr(unified_optimizer, "last_query_id") and unified_optimizer.last_query_id:
            print("- Visualizing query plan...")
            unified_optimizer.visualize_query_plan(show_plot=False, 
                                                output_file="/tmp/query_plan.png")
            print(f"  Query plan visualization saved to /tmp/query_plan.png")
            
            print("- Visualizing resource usage...")
            unified_optimizer.visualize_resource_usage(show_plot=False,
                                                    output_file="/tmp/resource_usage.png")
            print(f"  Resource usage visualization saved to /tmp/resource_usage.png")
            
            print("- Exporting metrics dashboard...")
            dashboard_path = unified_optimizer.visualize_metrics_dashboard(
                                                    output_file="/tmp/query_dashboard.html")
            print(f"  Metrics dashboard exported to {dashboard_path or '/tmp/query_dashboard.html'}")
            
        else:
            print("- No queries executed yet. Run queries first to enable visualizations.")
    
    # Demonstrate query rewriting (still relevant)
    original_query = {
        "entity_types": ["Person", "Organization"],
        "min_similarity": 0.4,
        "traversal": {
            "max_depth": 4,
            "edge_types": ["knows", "works_for", "founded"]
        }
    }
    
    rewritten = query_rewriter.rewrite_query(original_query, unified_optimizer.graph_info)
    print(f"Original Query: {json.dumps(original_query, indent=2)}")
    print(f"Rewritten Query: {json.dumps(rewritten, indent=2)}")
    
    # Demonstrate budget management
    budget = budget_manager.allocate_budget(query, priority="critical")
    print(f"Allocated Budget: {json.dumps(budget, indent=2)}")
    
    # Track some resource consumption
    budget_manager.track_consumption("vector_search_ms", 250.0)
    budget_manager.track_consumption("graph_traversal_ms", 800.0)
    budget_manager.track_consumption("nodes_visited", 500)
    
    # Get consumption report
    consumption_report = budget_manager.get_current_consumption_report()
    print(f"Consumption Report: {json.dumps(consumption_report, indent=2)}")
    
    return "Example completed successfully"


def test_query_rewriter_integration():
    """Test the integration between QueryRewriter and UnifiedGraphRAGQueryOptimizer."""
    # Create a unified optimizer with integrated rewriter
    unified_optimizer = UnifiedGraphRAGQueryOptimizer()
    
    # Verify that traversal stats are passed to the rewriter
    assert unified_optimizer.rewriter.traversal_stats is unified_optimizer._traversal_stats, \
        "Traversal stats reference not properly passed to rewriter"
    
    # Update some traversal stats to test the integration
    unified_optimizer._traversal_stats["relation_usefulness"]["instance_of"] = 0.9
    unified_optimizer._traversal_stats["relation_usefulness"]["part_of"] = 0.7
    unified_optimizer._traversal_stats["relation_usefulness"]["created_by"] = 0.3
    
    # Create a test query with traversal parameters
    query = {
        "query_vector": np.random.rand(768),
        "traversal": {
            "edge_types": ["created_by", "instance_of", "part_of"],
            "max_depth": 3
        }
    }
    
    # Get the optimized query plan
    optimized_plan = unified_optimizer.optimize_query(query)
    
    # Verify that the relation usefulness affected edge_types ordering in the rewritten query
    optimized_edge_types = optimized_plan["query"].get("traversal", {}).get("edge_types", [])
    
    # The most useful relation (instance_of) should be first if adaptive optimization worked
    if optimized_edge_types and len(optimized_edge_types) >= 3:
        print("Original edge types order:", query["traversal"]["edge_types"])
        print("Optimized edge types order:", optimized_edge_types)
        assert optimized_edge_types[0] == "instance_of", \
            "Relation usefulness not properly applied in edge_types reordering"
    
    # Test entity importance-based pruning
    # Create a mock graph processor for testing
    class MockGraphProcessor:
        def get_entity_info(self, entity_id) -> Dict[str, Any]:
            return {
                "inbound_connections": [{"id": i} for i in range(10)],
                "outbound_connections": [{"id": i} for i in range(5)],
                "properties": {"name": entity_id, "type": "test"},
                "type": "concept"
            }
    
    # Create a query with entity IDs
    entity_query = {
        "query_vector": np.random.rand(768),
        "entity_ids": ["entity1", "entity2", "entity3"],
        "traversal": {
            "edge_types": ["instance_of", "part_of"],
            "max_depth": 2
        }
    }
    
    # Run optimization with the mock processor
    optimized_plan = unified_optimizer.optimize_query(entity_query, graph_processor=MockGraphProcessor())
    
    # Check that entity scores were calculated and passed to the rewriter
    if "traversal" in optimized_plan["query"] and "entity_scores" in optimized_plan["query"]["traversal"]:
        print("Entity scores:", optimized_plan["query"]["traversal"]["entity_scores"])
        assert len(optimized_plan["query"]["traversal"]["entity_scores"]) > 0, \
            "Entity scores not properly calculated and passed to rewriter"
    
    print("QueryRewriter integration test completed successfully!")
    return True


if __name__ == "__main__":
    # Run the example usage function to demonstrate the RAG Query Optimizer
    example_usage()
    
    # Run the integration test
    try:
        test_query_rewriter_integration()
    except Exception as e:
        print(f"Integration test failed: {e}")
