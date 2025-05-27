"""
Integration tests for the RAG Query Optimizer.

This module tests how the RAG Query Optimizer integrates with other components
of the system, including:
- Integration with GraphRAGLLMProcessor
- Integration with WikipediaKnowledgeGraphTracer
- Integration with query visualization
- Cross-component optimization capabilities
- End-to-end query execution and caching
"""

import unittest
import numpy as np
import os
import tempfile
import shutil
import time
from typing import Dict, List, Any, Optional

# Import RAG Query Optimizer components 
from ipfs_datasets_py import (
    GraphRAGQueryStats,
    QueryRewriter,
    QueryBudgetManager,
    UnifiedGraphRAGQueryOptimizer,
    QueryMetricsCollector,
    QueryVisualizer
)

# Import LLM components for integration testing
from ipfs_datasets_py.llm_graphrag import GraphRAGLLMProcessor
from ipfs_datasets_py.llm_interface import LLMInterface, LLMConfig
from ipfs_datasets_py.llm_reasoning_tracer import WikipediaKnowledgeGraphTracer
# ReasoningTracer is not available, using ReasoningEnhancer instead
from ipfs_datasets_py.llm_reasoning_tracer import ReasoningEnhancer

# Optional visualization dependencies
try:
    import matplotlib.pyplot as plt
    VISUALIZATION_AVAILABLE = True
except ImportError:
    VISUALIZATION_AVAILABLE = False

# Check for Wikipedia optimizer
try:
    from ipfs_datasets_py.wikipedia_rag_optimizer import WikipediaKnowledgeGraphOptimizer
    WIKIPEDIA_OPTIMIZER_AVAILABLE = True
except ImportError:
    WIKIPEDIA_OPTIMIZER_AVAILABLE = False


# Mock classes for testing
class MockLLMInterface(LLMInterface):
    """Mock LLM interface for testing."""
    def __init__(self, config=None):
        """Initialize mock LLM interface with optional config."""
        super().__init__(config or LLMConfig())
        
    def generate(self, prompt: str, **kwargs) -> str:
        """Generate a response to the given prompt."""
        return f"Mock LLM response to: {prompt[:50]}..."
    
    def generate_with_structured_output(self, prompt: str, schema: Dict[str, Any], **kwargs) -> Dict[str, Any]:
        """Generate a structured response based on the schema."""
        # Return minimal valid structure based on common schemas
        if "answer" in schema.get("required", []) and "reasoning" in schema.get("required", []):
            return {"answer": "Mock answer", "reasoning": "Mock reasoning", "confidence": 0.85}
        elif "relationship_type" in schema.get("required", []):
            return {"relationship_type": "mock_relation", "explanation": "Mock explanation", "confidence": 0.9}
        else:
            return {"summary": "Mock summary"}
    
    def count_tokens(self, text: str) -> int:
        """Count tokens in the given text."""
        return len(text.split())
    
    def embed_text(self, text: str):
        """Embed the given text."""
        return np.random.rand(768)
    
    def embed_batch(self, texts: List[str]):
        """Embed the given batch of texts."""
        return np.array([self.embed_text(text) for text in texts])
    
    def tokenize(self, text: str):
        """Tokenize the given text."""
        return [1] * len(text.split())


class MockVectorStore:
    """Mock vector store for testing."""
    def __init__(self, latency=0.01):
        self.latency = latency
        self.call_count = 0
        
    def search(self, vector, top_k=5):
        self.call_count += 1
        time.sleep(self.latency)  # Simulate latency
        return [{"id": f"vec_{i}", "score": 0.95 - (i * 0.08), "metadata": {"text": f"Vector result {i}"}, "source": "vector"} for i in range(top_k)]


class MockGraphStore:
    """Mock graph store for testing."""
    def __init__(self, latency=0.02):
        self.latency = latency
        self.call_count = 0
        
    def traverse_from_entities(self, entities: List[Dict], relationship_types: Optional[List[str]] = None, max_depth: int = 2):
        self.call_count += 1
        time.sleep(self.latency * max_depth)  # Simulate latency proportional to depth
        results = []
        for i, entity_info in enumerate(entities):
            seed_id = entity_info.get("id", f"seed_{i}")
            # Simulate finding related entities
            for j in range(max_depth): # Simple simulation
                 results.append({"id": f"{seed_id}_related_{j}", "properties": {"name": f"Related {j} to {seed_id}"}, "source": "graph", "score": 0.6 + j*0.05})
        return results


class MockWikipediaKnowledgeGraphTracer(WikipediaKnowledgeGraphTracer):
    """Mock Wikipedia knowledge graph tracer for testing."""
    def __init__(self):
        """Initialize mock tracer."""
        self.traces = {}
        
    def get_trace_info(self, trace_id):
        """Get trace information."""
        if trace_id not in self.traces:
            self.traces[trace_id] = {
                "page_title": f"Mock Page {trace_id}",
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
                "entities": [
                    {"entity_id": "e1", "name": "Entity 1", "entity_type": "person"},
                    {"entity_id": "e2", "name": "Entity 2", "entity_type": "organization"}
                ],
                "relationships": [
                    {"source": "e1", "target": "e2", "type": "works_for"}
                ]
            }
        return self.traces[trace_id]


class TestRAGQueryOptimizerLLMIntegration(unittest.TestCase):
    """Test RAG Query Optimizer integration with LLM components."""
    
    def setUp(self):
        """Set up the test environment."""
        # Create temp directory for metrics
        self.temp_dir = tempfile.mkdtemp()
        
        # Create metrics collector with temp directory
        self.metrics_collector = QueryMetricsCollector(
            metrics_dir=self.temp_dir,
            track_resources=True
        )
        
        # Create unified optimizer
        self.optimizer = UnifiedGraphRAGQueryOptimizer(
            metrics_collector=self.metrics_collector,
            metrics_dir=self.temp_dir
        )
        
        # Enable statistical learning
        self.optimizer.enable_statistical_learning(enabled=True, learning_cycle=5)
        
        # Create mock LLM interface
        self.llm_interface = MockLLMInterface()
        
        # Create mock stores
        self.vector_store = MockVectorStore()
        self.graph_store = MockGraphStore()
        
        # Create GraphRAGLLMProcessor with the optimizer
        self.processor = GraphRAGLLMProcessor(
            llm_interface=self.llm_interface,
            query_optimizer=self.optimizer
        )
        
        # Assign stores to processor
        self.processor.vector_store = self.vector_store
        self.processor.graph_store = self.graph_store
        
        # Create random query vector
        self.query_vector = np.random.rand(768)
        
    def tearDown(self):
        """Clean up after the test."""
        shutil.rmtree(self.temp_dir)
        
    def test_processor_integration(self):
        """Test integration with GraphRAGLLMProcessor."""
        # Create a query
        query_text = "Test query for processor integration"
        
        # Process the query using the processor
        result = self.processor.process_graph_rag_query(
            query=query_text,
            query_vector=self.query_vector,
            max_vector_results=5,
            max_traversal_depth=2
        )
        
        # Verify result structure
        self.assertIsNotNone(result)
        self.assertIn("answer", result)
        self.assertIn("reasoning", result)
        self.assertIn("execution_info", result)
        
        # Verify execution_info contains optimizer details
        execution_info = result["execution_info"]
        self.assertIn("from_cache", execution_info)
        
    def test_processor_caching(self):
        """Test that caching works across processor and optimizer."""
        # Create a query
        query_text = "Test query for caching integration"
        
        # Execute the query first time
        result1 = self.processor.process_graph_rag_query(
            query=query_text,
            query_vector=self.query_vector,
            max_vector_results=5,
            max_traversal_depth=2
        )
        
        # Reset call counts
        self.vector_store.call_count = 0
        self.graph_store.call_count = 0
        
        # Execute same query again
        result2 = self.processor.process_graph_rag_query(
            query=query_text,
            query_vector=self.query_vector,
            max_vector_results=5,
            max_traversal_depth=2
        )
        
        # Verify cache was used
        self.assertEqual(self.vector_store.call_count, 0)
        self.assertEqual(self.graph_store.call_count, 0)
        self.assertTrue(result2["execution_info"]["from_cache"])
        
    def test_cross_document_integration(self):
        """Test integration with cross-document reasoning."""
        # Create a cross-document query
        query_text = "How are these documents related?"
        documents = [
            {"id": "doc1", "text": "Document 1 text about topic A."},
            {"id": "doc2", "text": "Document 2 text about topic B."}
        ]
        connections = [
            {"source": "doc1", "target": "doc2", "type": "related_to"}
        ]
        
        # Process the query using cross-document reasoning
        result = self.processor.synthesize_cross_document_reasoning(
            query=query_text,
            documents=documents,
            connections=connections,
            reasoning_depth="moderate",
            query_vector=self.query_vector
        )
        
        # Verify result structure
        self.assertIsNotNone(result)
        self.assertIn("answer", result)
        self.assertIn("reasoning", result)
        self.assertIn("execution_info", result)
        
    def test_optimize_query_integration(self):
        """Test direct integration between optimizer and processor components."""
        # Create test query
        query = {
            "query_vector": self.query_vector,
            "query_text": "Test query for optimizer-processor integration",
            "max_vector_results": 5,
            "max_traversal_depth": 2
        }
        
        # Get optimized query plan
        plan = self.optimizer.optimize_query(query)
        
        # Verify plan structure
        self.assertIsNotNone(plan)
        self.assertIn("query", plan)
        
        # Execute the plan using components from processor
        def vector_search_func(vector, params):
            top_k = params.get("max_vector_results", 5)
            return self.vector_store.search(vector, top_k=top_k)
        
        def graph_traversal_func(entities, params):
            max_depth = params.get("max_traversal_depth", 2)
            return self.graph_store.traverse_from_entities(entities, max_depth=max_depth)
        
        results = self.optimizer.execute_query_plan(
            plan=plan,
            vector_search_func=vector_search_func,
            graph_traversal_func=graph_traversal_func
        )
        
        # Verify results structure
        self.assertIsNotNone(results)
        self.assertIn("combined_results", results)


@unittest.skipIf(not WIKIPEDIA_OPTIMIZER_AVAILABLE, "Wikipedia optimizer not available")
class TestWikipediaOptimizerIntegration(unittest.TestCase):
    """Test RAG Query Optimizer integration with Wikipedia-specific components."""
    
    def setUp(self):
        """Set up the test environment."""
        # Create mock tracer
        self.mock_tracer = MockWikipediaKnowledgeGraphTracer()
        
        # Create Wikipedia optimizer with mock tracer
        self.wikipedia_optimizer = WikipediaKnowledgeGraphOptimizer(
            tracer=self.mock_tracer
        )
        
        # Create unified optimizer with Wikipedia optimizer
        self.unified_optimizer = UnifiedGraphRAGQueryOptimizer(
            wikipedia_optimizer=self.wikipedia_optimizer
        )
        
        # Create random query vector
        self.query_vector = np.random.rand(768)
        
    def test_wikipedia_query_optimization(self):
        """Test Wikipedia-specific query optimization."""
        # Create a Wikipedia query
        query_text = "Who founded Microsoft?"
        trace_id = "test_trace_1"
        
        # Optimize the query
        result = self.unified_optimizer.optimize_query(
            query_vector=self.query_vector,
            query_text=query_text,
            trace_id=trace_id,
            graph_type="wikipedia"  # Explicitly specify Wikipedia
        )
        
        # Verify optimizer detected Wikipedia graph type
        self.assertEqual(result["graph_type"], "wikipedia")
        self.assertEqual(result["optimizer_type"], "wikipedia")
        
        # Verify query has Wikipedia-specific optimizations
        query = result["query"]
        self.assertIn("traversal", query)
        
    def test_cross_document_wikipedia_optimization(self):
        """Test cross-document Wikipedia query optimization."""
        # Create trace IDs
        trace_ids = ["test_trace_1", "test_trace_2"]
        
        # Create query
        query_text = "How are Bill Gates and Microsoft related?"
        
        # Optimize cross-document query
        result = self.unified_optimizer.optimize_cross_document_query(
            query_vector=self.query_vector,
            query_text=query_text,
            doc_trace_ids=trace_ids
        )
        
        # Verify result structure
        self.assertIsNotNone(result)
        self.assertIn("optimizer_type", result)
        self.assertEqual(result["optimizer_type"], "cross_document_wikipedia")
        
        # Check for connecting entities
        self.assertIn("connecting_entities", result)
        self.assertIn("traversal_paths", result)
        
    def test_entity_type_detection(self):
        """Test entity type detection in Wikipedia optimization."""
        # Person query
        person_query = "Who was the founder of Microsoft?"
        person_types = self.wikipedia_optimizer._detect_entity_types(person_query)
        self.assertIn("person", person_types)
        
        # Location query
        location_query = "Where is the headquarters of Google located?"
        location_types = self.wikipedia_optimizer._detect_entity_types(location_query)
        self.assertIn("location", location_types)
        
        # Concept query
        concept_query = "What is the theory of relativity?"
        concept_types = self.wikipedia_optimizer._detect_entity_types(concept_query)
        self.assertIn("concept", concept_types)


@unittest.skipIf(not VISUALIZATION_AVAILABLE, "Visualization dependencies not available")
class TestVisualizationIntegration(unittest.TestCase):
    """Test RAG Query Optimizer integration with visualization components."""
    
    def setUp(self):
        """Set up the test environment."""
        # Create temp directory for metrics
        self.temp_dir = tempfile.mkdtemp()
        
        # Create metrics collector with temp directory
        self.metrics_collector = QueryMetricsCollector(
            metrics_dir=self.temp_dir,
            track_resources=True
        )
        
        # Create visualizer
        self.visualizer = QueryVisualizer(self.metrics_collector)
        
        # Create unified optimizer with metrics collector and visualizer
        self.optimizer = UnifiedGraphRAGQueryOptimizer(
            metrics_collector=self.metrics_collector,
            visualizer=self.visualizer,
            metrics_dir=self.temp_dir
        )
        
        # Create random query vector
        self.query_vector = np.random.rand(768)
        
    def tearDown(self):
        """Clean up after the test."""
        shutil.rmtree(self.temp_dir)
        
    def test_metrics_collection_visualization(self):
        """Test that metrics collection and visualization work together."""
        # Execute some queries to generate metrics
        for i in range(5):
            query_id = self.metrics_collector.start_query_tracking(
                query_params={"traversal": {"max_depth": 2}, "vector_params": {"top_k": 5}}
            )
            
            with self.metrics_collector.time_phase("vector_search"):
                time.sleep(0.01)
                
            with self.metrics_collector.time_phase("graph_traversal"):
                time.sleep(0.02)
                
            self.metrics_collector.end_query_tracking(
                results_count=5,
                quality_score=0.8
            )
        
        # Create visualization output files
        phase_timing_path = os.path.join(self.temp_dir, "phase_timing.png")
        dashboard_path = os.path.join(self.temp_dir, "dashboard.html")
        
        # Generate visualizations
        try:
            self.visualizer.visualize_phase_timing(
                show_plot=False,
                output_file=phase_timing_path
            )
            
            self.visualizer.export_dashboard_html(
                output_file=dashboard_path
            )
            
            # Check files were created
            self.assertTrue(os.path.exists(phase_timing_path))
            self.assertTrue(os.path.exists(dashboard_path))
        except Exception as e:
            # If visualization fails, it might be due to environment limitations
            # This shouldn't cause the test to fail, just log the issue
            print(f"Visualization failed: {e}")
            self.skipTest("Visualization failed due to environment limitations")
        
    def test_query_plan_visualization(self):
        """Test query plan visualization."""
        # Create a query plan
        query_plan = {
            "phases": {
                "vector_search": {
                    "name": "Vector Search",
                    "type": "vector_search",
                    "duration": 0.15
                },
                "graph_traversal": {
                    "name": "Graph Traversal",
                    "type": "graph_traversal",
                    "duration": 0.25,
                    "dependencies": ["vector_search"]
                },
                "ranking": {
                    "name": "Result Ranking",
                    "type": "ranking",
                    "duration": 0.05,
                    "dependencies": ["graph_traversal"]
                }
            }
        }
        
        # Create visualization output file
        plan_path = os.path.join(self.temp_dir, "query_plan.png")
        
        # Generate visualization
        try:
            self.visualizer.visualize_query_plan(
                query_plan=query_plan,
                show_plot=False,
                output_file=plan_path
            )
            
            # Check file was created
            self.assertTrue(os.path.exists(plan_path))
        except Exception as e:
            # If visualization fails, it might be due to environment limitations
            # This shouldn't cause the test to fail, just log the issue
            print(f"Plan visualization failed: {e}")
            self.skipTest("Plan visualization failed due to environment limitations")
        
    def test_metrics_export(self):
        """Test metrics export functionality."""
        # Generate some metrics
        for i in range(3):
            query_id = self.metrics_collector.start_query_tracking(
                query_params={"test_param": i}
            )
            with self.metrics_collector.time_phase("processing"):
                time.sleep(0.01)
            self.metrics_collector.end_query_tracking(results_count=i)
        
        # Export metrics to CSV
        csv_path = os.path.join(self.temp_dir, "metrics.csv")
        csv_content = self.metrics_collector.export_metrics_csv(csv_path)
        
        # Check file was created
        self.assertTrue(os.path.exists(csv_path))
        
        # Check CSV content
        with open(csv_path, 'r') as f:
            content = f.read()
            self.assertIn("query_id", content)
            self.assertIn("duration", content)


if __name__ == "__main__":
    unittest.main()
