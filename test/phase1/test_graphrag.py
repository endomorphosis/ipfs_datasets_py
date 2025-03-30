import os
import sys
import unittest
import tempfile
import shutil
import numpy as np
from typing import Dict, List, Any, Optional

# Add parent directory to path to import the module
parent_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
sys.path.append(parent_dir)

# Import the modules to test
try:
    from ipfs_datasets_py.dataset_serialization import GraphNode, GraphDataset, VectorAugmentedGraphDataset
    from ipfs_datasets_py.rag_query_optimizer import GraphRAGQueryOptimizer, GraphRAGQueryStats, VectorIndexPartitioner
    MODULE_AVAILABLE = True
except ImportError:
    MODULE_AVAILABLE = False

class TestGraphNode(unittest.TestCase):
    """Test the GraphNode class with edge property functionality."""
    
    def setUp(self):
        """Set up test fixtures before each test"""
        if not MODULE_AVAILABLE:
            self.skipTest("GraphNode module not available")
        
    def test_edge_properties(self):
        """Test adding and retrieving edges with properties"""
        # Create nodes
        node1 = GraphNode(node_id="1", node_type="person", properties={"name": "Alice"})
        node2 = GraphNode(node_id="2", node_type="person", properties={"name": "Bob"})
        node3 = GraphNode(node_id="3", node_type="document", properties={"title": "Report"})
        
        # Add edges with properties
        node1.add_edge("knows", node2, properties={"since": 2020, "relationship": "friend"})
        node1.add_edge("authored", node3, properties={"date": "2023-01-15", "role": "lead"})
        node2.add_edge("authored", node3, properties={"date": "2023-01-16", "role": "contributor"})
        
        # Test get_edges method
        edges = node1.get_edges("knows")
        self.assertEqual(len(edges), 1)
        self.assertEqual(edges[0]["target"].node_id, "2")
        self.assertEqual(edges[0]["properties"]["since"], 2020)
        self.assertEqual(edges[0]["properties"]["relationship"], "friend")
        
        # Test get_neighbors method
        neighbors = node1.get_neighbors()
        self.assertEqual(len(neighbors), 2)
        neighbor_ids = [n.node_id for n in neighbors]
        self.assertIn("2", neighbor_ids)
        self.assertIn("3", neighbor_ids)
        
        # Test get_edge_properties method
        edge_props = node1.get_edge_properties("authored", node3)
        self.assertEqual(edge_props["date"], "2023-01-15")
        self.assertEqual(edge_props["role"], "lead")
        
        # Test to_dict method includes edge properties
        node_dict = node1.to_dict()
        self.assertIn("edges", node_dict)
        self.assertIn("knows", node_dict["edges"])
        self.assertEqual(node_dict["edges"]["knows"][0]["properties"]["since"], 2020)

class TestGraphDataset(unittest.TestCase):
    """Test the GraphDataset class with edge property functionality."""
    
    def setUp(self):
        """Set up test fixtures before each test"""
        if not MODULE_AVAILABLE:
            self.skipTest("GraphDataset module not available")
        self.dataset = GraphDataset()
        
    def test_add_and_get_nodes(self):
        """Test adding and retrieving nodes"""
        # Add nodes
        node1 = self.dataset.add_node("person", {"name": "Alice", "age": 30})
        node2 = self.dataset.add_node("person", {"name": "Bob", "age": 35})
        node3 = self.dataset.add_node("document", {"title": "Report"})
        
        # Test getting nodes
        retrieved_node1 = self.dataset.get_node_by_id(node1)
        self.assertEqual(retrieved_node1.properties["name"], "Alice")
        
        # Test getting nodes by property
        age30_nodes = self.dataset.get_nodes_by_property("age", 30)
        self.assertEqual(len(age30_nodes), 1)
        self.assertEqual(age30_nodes[0].properties["name"], "Alice")
        
        # Test getting nodes by type
        person_nodes = self.dataset.get_nodes_by_type("person")
        self.assertEqual(len(person_nodes), 2)
        
    def test_edge_properties(self):
        """Test adding and retrieving edges with properties"""
        # Add nodes
        node1 = self.dataset.add_node("person", {"name": "Alice"})
        node2 = self.dataset.add_node("person", {"name": "Bob"})
        node3 = self.dataset.add_node("document", {"title": "Report"})
        
        # Add edges with properties
        self.dataset.add_edge(node1, "knows", node2, {"since": 2020, "relationship": "friend"})
        self.dataset.add_edge(node1, "authored", node3, {"date": "2023-01-15", "role": "lead"})
        self.dataset.add_edge(node2, "authored", node3, {"date": "2023-01-16", "role": "contributor"})
        
        # Test get_edges method
        edges = self.dataset.get_edges_by_type("knows")
        self.assertEqual(len(edges), 1)
        self.assertEqual(edges[0][0], node1)  # Source node
        self.assertEqual(edges[0][1], node2)  # Target node
        self.assertEqual(edges[0][2]["since"], 2020)  # Edge properties
        
        # Test getting edges by property
        lead_edges = self.dataset.get_edges_by_property("role", "lead")
        self.assertEqual(len(lead_edges), 1)
        self.assertEqual(lead_edges[0][0], node1)  # Source is Alice
        self.assertEqual(lead_edges[0][1], node3)  # Target is Report
        
    def test_traversal(self):
        """Test graph traversal with property filtering"""
        # Add nodes
        alice = self.dataset.add_node("person", {"name": "Alice"})
        bob = self.dataset.add_node("person", {"name": "Bob"})
        carol = self.dataset.add_node("person", {"name": "Carol"})
        report1 = self.dataset.add_node("document", {"title": "Report 1", "topic": "finance"})
        report2 = self.dataset.add_node("document", {"title": "Report 2", "topic": "technology"})
        
        # Add edges
        self.dataset.add_edge(alice, "knows", bob, {"relationship": "friend"})
        self.dataset.add_edge(bob, "knows", carol, {"relationship": "colleague"})
        self.dataset.add_edge(alice, "authored", report1, {"role": "lead"})
        self.dataset.add_edge(bob, "authored", report1, {"role": "contributor"})
        self.dataset.add_edge(carol, "authored", report2, {"role": "lead"})
        
        # Test traversal
        paths = self.dataset.traverse(alice, max_depth=2)
        self.assertEqual(len(paths), 4)  # Alice -> Bob, Alice -> Report1, Alice -> Bob -> Carol, Alice -> Bob -> Report1
        
        # Test traversal with edge type filter
        knows_paths = self.dataset.traverse(alice, max_depth=2, edge_types=["knows"])
        self.assertEqual(len(knows_paths), 2)  # Alice -> Bob, Alice -> Bob -> Carol
        
        # Test traversal with edge property filter
        lead_paths = self.dataset.traverse(
            alice, 
            max_depth=2, 
            edge_property_filters=[("role", "lead")]
        )
        self.assertEqual(len(lead_paths), 1)  # Alice -> Report1 (where Alice is lead)
        
    def test_find_paths(self):
        """Test finding paths between nodes"""
        # Add nodes
        alice = self.dataset.add_node("person", {"name": "Alice"})
        bob = self.dataset.add_node("person", {"name": "Bob"})
        carol = self.dataset.add_node("person", {"name": "Carol"})
        dave = self.dataset.add_node("person", {"name": "Dave"})
        
        # Add edges
        self.dataset.add_edge(alice, "knows", bob, {"relationship": "friend"})
        self.dataset.add_edge(bob, "knows", carol, {"relationship": "colleague"})
        self.dataset.add_edge(carol, "knows", dave, {"relationship": "friend"})
        self.dataset.add_edge(alice, "knows", dave, {"relationship": "family"})
        
        # Find paths from Alice to Dave
        paths = self.dataset.find_paths(alice, dave, max_depth=3)
        self.assertEqual(len(paths), 2)  # Direct path and path through Bob and Carol
        
        # Find paths with edge type filter
        paths_with_filter = self.dataset.find_paths(
            alice, 
            dave, 
            max_depth=3,
            edge_property_filters=[("relationship", "friend")]
        )
        # Should find at least the path through Bob and Carol, which has friend relationships
        self.assertGreaterEqual(len(paths_with_filter), 1)

class TestVectorAugmentedGraphDataset(unittest.TestCase):
    """Test the VectorAugmentedGraphDataset class."""
    
    def setUp(self):
        """Set up test fixtures before each test"""
        if not MODULE_AVAILABLE:
            self.skipTest("VectorAugmentedGraphDataset module not available")
        self.dataset = VectorAugmentedGraphDataset(vector_dimension=4)
        
    def test_node_vector_search(self):
        """Test adding nodes with vectors and searching"""
        # Add nodes with vectors
        node1 = self.dataset.add_node("document", {"title": "AI Research"}, vector=np.array([1.0, 0.0, 0.0, 0.0]))
        node2 = self.dataset.add_node("document", {"title": "ML Applications"}, vector=np.array([0.8, 0.2, 0.0, 0.0]))
        node3 = self.dataset.add_node("document", {"title": "Database Systems"}, vector=np.array([0.0, 0.0, 1.0, 0.0]))
        node4 = self.dataset.add_node("document", {"title": "Network Security"}, vector=np.array([0.0, 0.0, 0.0, 1.0]))
        
        # Add edges
        self.dataset.add_edge(node1, "cites", node2)
        self.dataset.add_edge(node2, "cites", node3)
        
        # Test vector search
        query_vector = np.array([0.9, 0.1, 0.0, 0.0])  # Similar to AI Research
        results = self.dataset.vector_search(query_vector, top_k=2)
        
        self.assertEqual(len(results), 2)
        # First result should be node1 (closest to query)
        self.assertEqual(results[0][0].properties["title"], "AI Research")
        # Second result should be node2
        self.assertEqual(results[1][0].properties["title"], "ML Applications")
        
    def test_graph_rag_search(self):
        """Test graph-enhanced RAG search"""
        # Add nodes with vectors
        node1 = self.dataset.add_node("document", {"title": "AI Research"}, vector=np.array([1.0, 0.0, 0.0, 0.0]))
        node2 = self.dataset.add_node("document", {"title": "ML Applications"}, vector=np.array([0.8, 0.2, 0.0, 0.0]))
        node3 = self.dataset.add_node("document", {"title": "Neural Networks"}, vector=np.array([0.7, 0.3, 0.0, 0.0]))
        node4 = self.dataset.add_node("document", {"title": "Database Systems"}, vector=np.array([0.0, 0.0, 1.0, 0.0]))
        
        # Add edges to create connections
        self.dataset.add_edge(node1, "related_to", node2, {"strength": 0.9})
        self.dataset.add_edge(node2, "related_to", node3, {"strength": 0.8})
        self.dataset.add_edge(node3, "references", node4, {"strength": 0.3})
        
        # Test GraphRAG search
        query_vector = np.array([0.9, 0.1, 0.0, 0.0])  # Similar to AI Research
        results = self.dataset.graph_rag_search(
            query_vector, 
            max_vector_results=2,
            max_traversal_depth=1,
            edge_types=["related_to"],
            min_similarity=0.5
        )
        
        # Should return node1 and node2 (node1 from vector search, node2 from traversal)
        self.assertEqual(len(results), 2)
        result_titles = [r[0].properties["title"] for r in results]
        self.assertIn("AI Research", result_titles)
        self.assertIn("ML Applications", result_titles)
        
    def test_query_optimization(self):
        """Test query optimization functionality"""
        # Enable query optimization
        self.dataset.enable_query_optimization()
        
        # Add nodes with vectors
        for i in range(10):
            self.dataset.add_node(
                "document", 
                {"title": f"Document {i}"}, 
                vector=np.random.rand(4)
            )
        
        # Perform queries to build statistics
        for _ in range(5):
            query_vector = np.random.rand(4)
            self.dataset.graph_rag_search(query_vector, use_optimizer=True)
        
        # Get stats
        optimizer = self.dataset.query_optimizer
        stats = optimizer.query_stats
        
        # Check that statistics were collected
        self.assertGreater(stats.query_count, 0)
        
    def test_vector_partitioning(self):
        """Test vector index partitioning"""
        # Skip if partitioning not implemented
        if not hasattr(self.dataset, 'enable_vector_partitioning'):
            self.skipTest("Vector partitioning not implemented")
            
        # Enable vector partitioning
        self.dataset.enable_vector_partitioning(num_partitions=2)
        
        # Add nodes with vectors in different regions of space
        node1 = self.dataset.add_node("document", {"title": "Document 1"}, vector=np.array([1.0, 0.0, 0.0, 0.0]))
        node2 = self.dataset.add_node("document", {"title": "Document 2"}, vector=np.array([0.9, 0.1, 0.0, 0.0]))
        node3 = self.dataset.add_node("document", {"title": "Document 3"}, vector=np.array([0.0, 0.0, 1.0, 0.0]))
        node4 = self.dataset.add_node("document", {"title": "Document 4"}, vector=np.array([0.0, 0.0, 0.9, 0.1]))
        
        # Test vector search using partitioning
        query_vector = np.array([0.95, 0.05, 0.0, 0.0])
        results = self.dataset.vector_search(query_vector, top_k=2)
        
        # Should return the two closest vectors
        self.assertEqual(len(results), 2)
        # Results should be node1 and node2
        result_titles = [r[0].properties["title"] for r in results]
        self.assertIn("Document 1", result_titles)
        self.assertIn("Document 2", result_titles)

class TestGraphRAGQueryOptimizer(unittest.TestCase):
    """Test the GraphRAGQueryOptimizer class."""
    
    def setUp(self):
        """Set up test fixtures before each test"""
        if not MODULE_AVAILABLE:
            self.skipTest("GraphRAGQueryOptimizer module not available")
        self.stats = GraphRAGQueryStats()
        self.optimizer = GraphRAGQueryOptimizer(self.stats)
        
    def test_query_stats(self):
        """Test collection of query statistics"""
        # Record some query stats
        self.stats.record_query_time(0.1)
        self.stats.record_query_time(0.2)
        self.stats.record_query_time(0.15)
        
        # Check stats
        self.assertEqual(self.stats.query_count, 3)
        self.assertAlmostEqual(self.stats.avg_query_time, 0.15)
        
        # Record cache hit
        self.stats.record_cache_hit()
        self.stats.record_cache_hit()
        
        # Check cache hit rate
        self.assertEqual(self.stats.cache_hits, 2)
        self.assertAlmostEqual(self.stats.cache_hit_rate, 2/5)  # 2 hits out of 5 total queries
        
    def test_query_optimization(self):
        """Test query optimization capabilities"""
        # Mock query parameters
        query_vector = np.array([1.0, 0.0, 0.0, 0.0])
        max_vector_results = 10
        max_traversal_depth = 2
        edge_types = ["related_to", "references"]
        min_similarity = 0.7
        
        # Get optimized parameters
        optimized_params = self.optimizer.optimize_query(
            query_vector,
            max_vector_results,
            max_traversal_depth,
            edge_types,
            min_similarity
        )
        
        # Check that optimizer returns a dictionary with expected keys
        self.assertIsInstance(optimized_params, dict)
        self.assertIn("max_vector_results", optimized_params)
        self.assertIn("max_traversal_depth", optimized_params)
        self.assertIn("min_similarity", optimized_params)
        
        # Test query caching
        query_key = self.optimizer.get_query_key(
            query_vector,
            max_vector_results,
            max_traversal_depth,
            edge_types,
            min_similarity
        )
        
        # Add a mock result to the cache
        mock_result = [("node1", 0.9, []), ("node2", 0.8, [])]
        self.optimizer.add_to_cache(query_key, mock_result)
        
        # Check cache has the entry
        self.assertTrue(self.optimizer.is_in_cache(query_key))
        
        # Get from cache
        cached_result = self.optimizer.get_from_cache(query_key)
        self.assertEqual(cached_result, mock_result)

class TestVectorIndexPartitioner(unittest.TestCase):
    """Test the VectorIndexPartitioner class."""
    
    def setUp(self):
        """Set up test fixtures before each test"""
        if not MODULE_AVAILABLE:
            self.skipTest("VectorIndexPartitioner module not available")
        self.partitioner = VectorIndexPartitioner(dimension=2, num_partitions=2)
        
    def test_partitioning(self):
        """Test vector partitioning functionality"""
        # Add vectors to the partitioner
        vectors = [
            np.array([1.0, 0.0]),  # Should go to partition 0
            np.array([0.9, 0.1]),  # Should go to partition 0
            np.array([0.0, 1.0]),  # Should go to partition 1
            np.array([0.1, 0.9])   # Should go to partition 1
        ]
        
        # Get partition assignments
        partitions = [self.partitioner.assign_partition(v) for v in vectors]
        
        # Check that similar vectors are assigned to the same partition
        self.assertEqual(partitions[0], partitions[1])  # First two vectors should be in same partition
        self.assertEqual(partitions[2], partitions[3])  # Last two vectors should be in same partition
        self.assertNotEqual(partitions[0], partitions[2])  # Different vector groups should be in different partitions
        
    def test_search(self):
        """Test partitioned search functionality"""
        # Create vectors
        vectors = [
            np.array([1.0, 0.0]),
            np.array([0.9, 0.1]),
            np.array([0.0, 1.0]),
            np.array([0.1, 0.9])
        ]
        metadata = [f"vector_{i}" for i in range(len(vectors))]
        
        # Add vectors to partitioner
        for i, vector in enumerate(vectors):
            self.partitioner.add_vector(vector, metadata[i])
        
        # Search in partitioned space
        query = np.array([0.95, 0.05])
        results = self.partitioner.search(query, top_k=2)
        
        # Check results
        self.assertEqual(len(results), 2)
        # Results should be the first two vectors (closest to query)
        result_metadata = [r[1] for r in results]
        self.assertIn("vector_0", result_metadata)
        self.assertIn("vector_1", result_metadata)

if __name__ == '__main__':
    unittest.main()