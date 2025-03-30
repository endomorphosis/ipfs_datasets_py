import os
import sys
import unittest
import numpy as np
from typing import Dict, List, Any, Optional

# Add parent directory to path to import the module
parent_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
sys.path.append(parent_dir)

# Import the modules to test
try:
    from ipfs_datasets_py.dataset_serialization import GraphNode, GraphDataset, VectorAugmentedGraphDataset
    MODULE_AVAILABLE = True
except ImportError:
    MODULE_AVAILABLE = False

class TestAdvancedGraphRAGMethods(unittest.TestCase):
    """Test the advanced GraphRAG methods in VectorAugmentedGraphDataset."""
    
    def setUp(self):
        """Set up test fixtures before each test"""
        if not MODULE_AVAILABLE:
            self.skipTest("VectorAugmentedGraphDataset module not available")
        self.dataset = VectorAugmentedGraphDataset(vector_dimension=4)
        
        # Add nodes with vectors for testing
        self.ai_paper = self.dataset.add_node("paper", {"title": "Advances in Neural Networks", "year": 2020, "citation_count": 50}, 
                               vector=np.array([1.0, 0.0, 0.0, 0.0]))
        self.ml_paper = self.dataset.add_node("paper", {"title": "Machine Learning Applications", "year": 2018, "citation_count": 100}, 
                               vector=np.array([0.8, 0.2, 0.0, 0.0]))
        self.dl_paper = self.dataset.add_node("paper", {"title": "Deep Learning Survey", "year": 2019, "citation_count": 75}, 
                              vector=np.array([0.7, 0.3, 0.0, 0.0]))
        self.cv_paper = self.dataset.add_node("paper", {"title": "Computer Vision Trends", "year": 2021, "citation_count": 25}, 
                              vector=np.array([0.6, 0.2, 0.2, 0.0]))
        self.db_paper = self.dataset.add_node("paper", {"title": "Database Systems Overview", "year": 2017, "citation_count": 120}, 
                               vector=np.array([0.0, 0.0, 1.0, 0.0]))
        
        # Add edges to create connections with edge properties
        self.dataset.add_edge(self.ai_paper, "cites", self.ml_paper, {"importance": "high", "section": "methods"})
        self.dataset.add_edge(self.ai_paper, "cites", self.dl_paper, {"importance": "medium", "section": "background"})
        self.dataset.add_edge(self.ml_paper, "cites", self.db_paper, {"importance": "low", "section": "implementation"})
        self.dataset.add_edge(self.dl_paper, "references", self.ml_paper, {"count": 5})
        self.dataset.add_edge(self.cv_paper, "cites", self.ai_paper, {"importance": "high", "section": "related_work"})
        self.dataset.add_edge(self.cv_paper, "cites", self.dl_paper, {"importance": "high", "section": "methods"})
    
    def test_find_similar_connected_nodes(self):
        """Test finding nodes that are both semantically similar and connected by specific relationship patterns"""
        # Query vector similar to AI and ML papers
        query_vector = np.array([0.9, 0.1, 0.0, 0.0])
        
        # Find similar connected nodes with edge filters
        results = self.dataset.find_similar_connected_nodes(
            query_vector=query_vector,
            max_hops=2,
            min_similarity=0.6,
            edge_filters=[("importance", "=", "high")],
            max_results=5
        )
        
        # Should find at least the path from ai_paper to ml_paper with high importance
        self.assertGreaterEqual(len(results), 1)
        
        # Check structure of results
        for result in results:
            self.assertIn("start_node", result)
            self.assertIn("end_node", result)
            self.assertIn("path", result)
            self.assertIn("combined_score", result)
            
        # Check that all returned paths have the edge property we filtered for
        for result in results:
            path = result["path"]
            for step in path:
                if len(step) >= 3 and step[2] is not None and "importance" in step[2]:
                    self.assertEqual(step[2]["importance"], "high")
    
    def test_semantic_subgraph(self):
        """Test extracting a subgraph containing semantically similar nodes and their connections"""
        # Query vector similar to AI and ML papers
        query_vector = np.array([0.9, 0.1, 0.0, 0.0])
        
        # Extract semantic subgraph
        subgraph = self.dataset.semantic_subgraph(
            query_vector=query_vector,
            similarity_threshold=0.6,
            include_connections=True,
            max_distance=2
        )
        
        # Should be a graph dataset
        self.assertIsInstance(subgraph, GraphDataset)
        
        # Should contain the AI, ML, and DL papers which are similar to the query
        node_titles = [node.properties.get("title") for node in subgraph.nodes.values()]
        self.assertIn("Advances in Neural Networks", node_titles)
        self.assertIn("Machine Learning Applications", node_titles)
        self.assertIn("Deep Learning Survey", node_titles)
        
        # Should also include some edges between these nodes
        self.assertGreaterEqual(len(subgraph.get_edges_by_type("cites")), 1)
    
    def test_logical_query(self):
        """Test performing logical operations with multiple query vectors"""
        # Create query vectors
        ai_vector = np.array([0.9, 0.1, 0.0, 0.0])  # Similar to AI papers
        cv_vector = np.array([0.6, 0.2, 0.2, 0.0])  # Similar to CV papers
        db_vector = np.array([0.0, 0.0, 0.9, 0.1])  # Similar to DB papers
        
        # Test AND operation
        and_results = self.dataset.logical_query(
            query_vectors=[ai_vector, cv_vector],
            operators=["AND"],
            similarity_threshold=0.6
        )
        
        # Should find nodes similar to both AI and CV vectors
        self.assertGreaterEqual(len(and_results), 1)
        
        # Test OR operation
        or_results = self.dataset.logical_query(
            query_vectors=[ai_vector, db_vector],
            operators=["OR"],
            similarity_threshold=0.7
        )
        
        # Should find nodes similar to either AI or DB vectors
        # Which should be more than either individual query
        ai_results = self.dataset.vector_search(ai_vector)
        ai_results = [(node, score) for node, score in ai_results if score >= 0.7]
        db_results = self.dataset.vector_search(db_vector)
        db_results = [(node, score) for node, score in db_results if score >= 0.7]
        
        self.assertGreaterEqual(len(or_results), max(len(ai_results), len(db_results)))
        
        # Test NOT operation
        not_results = self.dataset.logical_query(
            query_vectors=[ai_vector, db_vector],
            operators=["NOT"],
            similarity_threshold=0.7
        )
        
        # Should find nodes similar to AI but not DB
        self.assertLessEqual(len(not_results), len(ai_results))
    
    def test_incremental_graph_update(self):
        """Test incrementally updating the graph while maintaining vector indices"""
        # Create new nodes and edges to add
        new_paper = GraphNode(id="new_paper", type="paper", 
                            data={"title": "New Research Paper", "year": 2022, "citation_count": 10})
        new_edges = [
            (self.ai_paper, "cites", "new_paper", {"importance": "medium"})
        ]
        
        # Create nodes and edges to remove
        nodes_to_remove = [self.db_paper]
        edges_to_remove = [(self.ml_paper, "cites", self.db_paper)]
        
        # Initial counts
        initial_node_count = len(self.dataset.nodes)
        initial_edge_count = sum(len(edges) for edges in self.dataset._edges_by_type.values())
        
        # Perform incremental update
        nodes_added, edges_added, nodes_removed, edges_removed = self.dataset.incremental_graph_update(
            nodes_to_add=[new_paper],
            edges_to_add=new_edges,
            nodes_to_remove=[self.db_paper],
            edges_to_remove=edges_to_remove,
            maintain_index=True
        )
        
        # Verify counts
        self.assertEqual(nodes_added, 1)
        self.assertEqual(edges_added, 1)
        self.assertEqual(nodes_removed, 1)
        self.assertEqual(edges_removed, 1)
        
        # Verify new node is in graph
        self.assertIn("new_paper", self.dataset.nodes)
        
        # Verify removed node is not in graph
        self.assertNotIn(self.db_paper, self.dataset.nodes)
        
        # Verify new edge exists
        edges = self.dataset.get_edges_by_type("cites")
        self.assertTrue(any(source.id == self.ai_paper and target.id == "new_paper" for source, target, _ in edges))
        
        # Final counts should be consistent
        final_node_count = len(self.dataset.nodes)
        final_edge_count = sum(len(edges) for edges in self.dataset._edges_by_type.values())
        
        self.assertEqual(final_node_count, initial_node_count)  # +1 -1 = no change
        self.assertEqual(final_edge_count, initial_edge_count)  # +1 -1 = no change
    
    def test_explain_path(self):
        """Test generating explanations for paths between nodes in the graph"""
        # Get path explanations
        explanations = self.dataset.explain_path(
            start_node_id=self.cv_paper,
            end_node_id=self.db_paper,
            max_paths=3,
            max_depth=3
        )
        
        # Should find at least one path
        self.assertGreaterEqual(len(explanations), 1)
        
        # Check structure of explanations
        for explanation in explanations:
            self.assertIn("nodes", explanation)
            self.assertIn("edges", explanation)
            self.assertIn("explanation", explanation)
            self.assertIn("confidence", explanation)
            
            # Explanation should be a non-empty string
            self.assertGreater(len(explanation["explanation"]), 0)
            
    def test_hybrid_structured_semantic_search(self):
        """Test hybrid search combining semantic similarity with structured filters and graph patterns"""
        # Query vector similar to AI/ML papers
        query_vector = np.array([0.9, 0.1, 0.0, 0.0])
        
        # Create node filters for high-citation papers
        node_filters = [
            ("citation_count", ">=", 50),  # High citation papers
            ("year", ">", 2018)  # Recent papers
        ]
        
        # Create relationship patterns for papers that cite other papers with high importance
        relationship_patterns = [
            {
                "direction": "outgoing",
                "edge_type": "cites",
                "edge_filters": [
                    ("importance", "=", "high")
                ]
            }
        ]
        
        # Perform hybrid search
        results = self.dataset.hybrid_structured_semantic_search(
            query_vector=query_vector,
            node_filters=node_filters,
            relationship_patterns=relationship_patterns,
            max_results=5,
            min_similarity=0.6
        )
        
        # Should find at least one result
        self.assertGreaterEqual(len(results), 1)
        
        # Check structure of results
        for result in results:
            self.assertIn("node", result)
            self.assertIn("similarity", result)
            self.assertIn("matches_filters", result)
            self.assertIn("matches_patterns", result)
            
            # Verify node properties match our filters
            node_data = result["node"]["data"]
            self.assertGreaterEqual(node_data["citation_count"], 50)
            self.assertGreater(node_data["year"], 2018)
            
            # Pattern matching was required
            self.assertTrue(result["matches_patterns"])
            
    def test_rank_nodes_by_centrality(self):
        """Test ranking nodes by their centrality in the graph with PageRank"""
        # First test basic PageRank without query influence
        centrality_results = self.dataset.rank_nodes_by_centrality()
        
        # Should return all nodes
        self.assertEqual(len(centrality_results), len(self.dataset.nodes))
        
        # Verify structure of results
        for node, score in centrality_results:
            self.assertIsInstance(node, GraphNode)
            self.assertIsInstance(score, float)
            self.assertGreaterEqual(score, 0)
            self.assertLessEqual(score, 1)
        
        # Now test with query influence
        query_vector = np.array([0.9, 0.1, 0.0, 0.0])  # Similar to AI papers
        centrality_results = self.dataset.rank_nodes_by_centrality(
            query_vector=query_vector,
            damping_by_similarity=True,
            weight_by_edge_properties={"cites": "importance"}
        )
        
        # Should still return all nodes
        self.assertEqual(len(centrality_results), len(self.dataset.nodes))
        
        # AI-related papers should be ranked higher now
        top_node = centrality_results[0][0]
        self.assertIn("AI", top_node.data.get("keywords", []) + 
                     [word for word in top_node.data.get("title", "").split() if word.lower() in ("ai", "neural", "learning")])
        
    def test_multi_hop_inference(self):
        """Test inferring multi-hop relationships that aren't explicitly in the graph"""
        # Test inferring potential collaborators based on citation patterns
        results = self.dataset.multi_hop_inference(
            start_node_id=self.ai_paper,
            relationship_pattern=["authored_by", "authored", "cites", "authored_by"],
            confidence_threshold=0.2,
            max_results=5
        )
        
        # Should find potential collaborators
        self.assertGreaterEqual(len(results), 1)
        
        # Check structure of results
        for result in results:
            self.assertIn("start_node", result)
            self.assertIn("end_node", result)
            self.assertIn("path", result)
            self.assertIn("confidence", result)
            self.assertIn("inferred_relationship", result)
            
            # Start node should be what we provided
            self.assertEqual(result["start_node"].id, self.ai_paper)
            
            # End node should be an author
            self.assertEqual(result["end_node"].type, "person")
            
            # Path should follow our pattern
            path = result["path"]
            self.assertGreaterEqual(len(path), 4)  # At least start, author1, paper, author2
            
            # Confidence should be within range
            self.assertGreaterEqual(result["confidence"], 0.2)
            self.assertLessEqual(result["confidence"], 1.0)
            
    def test_find_entity_clusters(self):
        """Test finding clusters of semantically similar and structurally connected entities"""
        # Find entity clusters
        clusters = self.dataset.find_entity_clusters(
            similarity_threshold=0.6,
            min_community_size=2,
            max_communities=5,
            relationship_weight=0.3
        )
        
        # Should find at least one cluster
        self.assertGreaterEqual(len(clusters), 1)
        
        # Check structure of clusters
        for cluster in clusters:
            self.assertIn("nodes", cluster)
            self.assertIn("size", cluster)
            self.assertIn("cohesion", cluster)
            self.assertIn("themes", cluster)
            
            # Size should match nodes length
            self.assertEqual(cluster["size"], len(cluster["nodes"]))
            self.assertGreaterEqual(cluster["size"], 2)
            
            # Cohesion should be in valid range
            self.assertGreaterEqual(cluster["cohesion"], 0.0)
            self.assertLessEqual(cluster["cohesion"], 1.0)
            
            # Check that nodes in the cluster are semantically related
            for node in cluster["nodes"]:
                self.assertIsInstance(node, GraphNode)
                node_id = node.id
                # Node should be in the dataset
                self.assertIn(node_id, self.dataset.nodes)
    
    def test_expand_query(self):
        """Test query expansion using the knowledge graph"""
        # Original query vector similar to ML papers
        query_vector = np.array([0.8, 0.2, 0.0, 0.0])
        
        # Test different expansion strategies
        expansion_strategies = ["neighbor_vectors", "cluster_centroids", "concept_enrichment"]
        
        for strategy in expansion_strategies:
            # Expand the query
            expanded_query = self.dataset.expand_query(
                query_vector=query_vector,
                expansion_strategy=strategy,
                expansion_factor=0.3,
                max_terms=2,
                min_similarity=0.6
            )
            
            # Check that the result is a valid vector
            self.assertIsInstance(expanded_query, np.ndarray)
            self.assertEqual(expanded_query.shape, query_vector.shape)
            
            # Expanded query should be normalized
            self.assertAlmostEqual(np.linalg.norm(expanded_query), 1.0, places=5)
            
            # The expanded query should be different from the original
            self.assertFalse(np.array_equal(expanded_query, query_vector))
            
            # But it should still be similar to the original
            similarity = np.dot(expanded_query, query_vector)
            self.assertGreater(similarity, 0.6)  # Should maintain reasonable similarity
            
        # Test with parameters that should return the original vector
        unchanged_query = self.dataset.expand_query(
            query_vector=query_vector,
            min_similarity=1.0  # No vectors will match this threshold
        )
        
        # Should return the original vector (normalized)
        self.assertTrue(np.allclose(unchanged_query, query_vector / np.linalg.norm(query_vector)))
        
    def test_resolve_entities(self):
        """Test entity resolution for identifying duplicate/equivalent entities"""
        # Create a set of potentially duplicate entities
        # First, we need the original entities from the dataset
        papers = [node for node in self.dataset.nodes.values() if node.type == "paper"]
        
        # Create some similar/duplicate entities
        duplicate_papers = []
        for i, paper in enumerate(papers[:2]):  # Take first two papers
            # Create a duplicate with slightly different properties
            dup_paper = GraphNode(
                id=f"duplicate_{paper.id}",
                type="paper",
                data={
                    "title": paper.data["title"] + " (Preprint)",  # Slightly modified title
                    "year": paper.data["year"],
                    "citation_count": paper.data["citation_count"] - 5  # Slightly different count
                }
            )
            # Add the same vector embedding as the original
            if paper.id in self.dataset._node_to_vector_idx:
                idx = self.dataset._node_to_vector_idx[paper.id]
                if self.dataset.vector_index._faiss_available:
                    vector = self.dataset.vector_index._index.reconstruct(idx)
                else:
                    vector = np.vstack(self.dataset.vector_index._vectors)[idx]
                
                # Add the duplicate paper with the same vector
                self.dataset.add_node_with_embedding(dup_paper, vector)
                duplicate_papers.append(dup_paper)
        
        # Add the duplicates to our candidate list
        candidate_nodes = papers[:2] + duplicate_papers
        
        # Test vector similarity-based resolution
        entity_groups = self.dataset.resolve_entities(
            candidate_nodes=candidate_nodes,
            resolution_strategy="vector_similarity",
            similarity_threshold=0.9
        )
        
        # Should find groups of duplicates
        self.assertGreaterEqual(len(entity_groups), 2)  # At least two groups
        
        # Check structure of groups
        for canonical_id, group in entity_groups.items():
            # Each group should have at least one node
            self.assertGreaterEqual(len(group), 1)
            
            # All nodes in a group should be the same type
            node_types = set(node.type for node in group)
            self.assertEqual(len(node_types), 1)
            
            # Check if original and duplicate are in the same group
            if len(group) > 1:
                # Get IDs without the "duplicate_" prefix
                original_ids = [node.id for node in group if not node.id.startswith("duplicate_")]
                duplicate_ids = [node.id.replace("duplicate_", "") for node in group if node.id.startswith("duplicate_")]
                
                # There should be overlap between original and duplicate IDs
                self.assertTrue(set(original_ids) & set(duplicate_ids))
        
        # Test property-based resolution
        prop_entity_groups = self.dataset.resolve_entities(
            candidate_nodes=candidate_nodes,
            resolution_strategy="property_matching",
            similarity_threshold=0.7,
            property_weights={"title": 0.7, "year": 0.3}
        )
        
        # Should also find groups
        self.assertGreaterEqual(len(prop_entity_groups), 1)
        
        # Test hybrid resolution
        hybrid_entity_groups = self.dataset.resolve_entities(
            candidate_nodes=candidate_nodes,
            resolution_strategy="hybrid",
            similarity_threshold=0.8
        )
        
        # Should also find groups
        self.assertGreaterEqual(len(hybrid_entity_groups), 1)
        
    def test_generate_contextual_embeddings(self):
        """Test generating contextual embeddings that incorporate graph structure"""
        # We'll test with a paper node that has connections
        papers = [node_id for node_id, node in self.dataset.nodes.items() if node.type == "paper"]
        
        if not papers:
            self.skipTest("No paper nodes found in dataset")
            
        paper_id = papers[0]
        
        # Test different context strategies
        context_strategies = ["neighborhood", "weighted_edges", "type_specific"]
        
        for strategy in context_strategies:
            # Generate a contextual embedding
            contextual_embedding = self.dataset.generate_contextual_embeddings(
                node_id=paper_id,
                context_strategy=strategy,
                context_depth=1
            )
            
            # Check that we got a valid embedding
            self.assertIsNotNone(contextual_embedding)
            self.assertIsInstance(contextual_embedding, np.ndarray)
            
            # Should match the vector dimension
            self.assertEqual(len(contextual_embedding), self.dataset.vector_index.dimension)
            
            # Should be normalized
            self.assertAlmostEqual(np.linalg.norm(contextual_embedding), 1.0, places=5)
            
            # Get the original embedding for comparison
            idx = self.dataset._node_to_vector_idx[paper_id]
            if self.dataset.vector_index._faiss_available:
                original_embedding = self.dataset.vector_index._index.reconstruct(idx)
            else:
                original_embedding = np.vstack(self.dataset.vector_index._vectors)[idx]
                
            # Normalize the original for fair comparison
            original_embedding = original_embedding / np.linalg.norm(original_embedding)
            
            # The contextual embedding should be different from the original
            # but still reasonably similar
            similarity = np.dot(contextual_embedding, original_embedding)
            self.assertGreater(similarity, 0.5)  # Should maintain core meaning
            self.assertLess(similarity, 1.0)  # Should be different due to context
            
        # Test with a non-existent node ID
        invalid_embedding = self.dataset.generate_contextual_embeddings(
            node_id="non_existent_id",
            context_strategy="neighborhood"
        )
        
        # Should return None for invalid node
        self.assertIsNone(invalid_embedding)

    def test_compare_subgraphs(self):
        """Test comparing two subgraphs for similarity"""
        # Create two overlapping subgraphs
        papers = [node for node in self.dataset.nodes.values() if node.type == "paper"]
        
        if len(papers) < 4:
            self.skipTest("Not enough paper nodes for subgraph comparison test")
        
        # Create first subgraph with AI and ML papers
        subgraph1 = GraphDataset(name="subgraph1")
        subgraph1.add_node(self.dataset.nodes[self.ai_paper])
        subgraph1.add_node(self.dataset.nodes[self.ml_paper])
        subgraph1.add_edge(self.ai_paper, "cites", self.ml_paper, {"importance": "high"})
        
        # Create second subgraph with ML and CV papers
        subgraph2 = GraphDataset(name="subgraph2")
        subgraph2.add_node(self.dataset.nodes[self.ml_paper])
        subgraph2.add_node(self.dataset.nodes[self.cv_paper])
        subgraph2.add_edge(self.cv_paper, "cites", self.ml_paper, {"importance": "medium"})
        
        # Test structural comparison
        structural_comparison = self.dataset.compare_subgraphs(
            subgraph1=subgraph1,
            subgraph2=subgraph2,
            comparison_method="structural"
        )
        
        # Verify structure of results
        self.assertIn("overall_similarity", structural_comparison)
        self.assertIn("structural_similarity", structural_comparison)
        self.assertIn("semantic_similarity", structural_comparison)
        self.assertIn("node_type_overlap", structural_comparison)
        self.assertIn("edge_type_overlap", structural_comparison)
        self.assertIn("shared_nodes", structural_comparison)
        
        # Should have one shared node (ML paper)
        self.assertEqual(len(structural_comparison["shared_nodes"]), 1)
        self.assertEqual(structural_comparison["shared_nodes"][0], self.ml_paper)
        
        # Should have correct unique nodes
        self.assertEqual(len(structural_comparison["unique_nodes1"]), 1)
        self.assertEqual(structural_comparison["unique_nodes1"][0], self.ai_paper)
        self.assertEqual(len(structural_comparison["unique_nodes2"]), 1)
        self.assertEqual(structural_comparison["unique_nodes2"][0], self.cv_paper)
        
        # Test semantic comparison
        semantic_comparison = self.dataset.compare_subgraphs(
            subgraph1=subgraph1,
            subgraph2=subgraph2,
            comparison_method="semantic"
        )
        
        # Semantic comparison should be different from structural
        self.assertNotEqual(
            semantic_comparison["overall_similarity"],
            structural_comparison["overall_similarity"]
        )
        
        # Test hybrid comparison with custom weights
        hybrid_comparison = self.dataset.compare_subgraphs(
            subgraph1=subgraph1,
            subgraph2=subgraph2,
            comparison_method="hybrid",
            semantic_weight=0.7,
            structural_weight=0.3,
            node_type_weights={"paper": 1.0}
        )
        
        # Verify that weights were applied
        expected_hybrid = (
            0.7 * semantic_comparison["semantic_similarity"] + 
            0.3 * structural_comparison["structural_similarity"]
        )
        self.assertAlmostEqual(hybrid_comparison["overall_similarity"], expected_hybrid, places=5)

    def test_temporal_graph_analysis(self):
        """Test analyzing the graph evolution over time periods"""
        # Add time property (year) to nodes for testing
        years = {
            self.ai_paper: 2018,
            self.ml_paper: 2019,
            self.dl_paper: 2020,
            self.cv_paper: 2021,
            self.db_paper: 2022
        }
        
        for node_id, year in years.items():
            node = self.dataset.nodes[node_id]
            node.data["year"] = year
        
        # Define time intervals for analysis
        time_intervals = [
            (2018, 2019),  # Early papers
            (2020, 2022)   # Recent papers
        ]
        
        # Perform temporal analysis
        results = self.dataset.temporal_graph_analysis(
            time_property="year",
            time_intervals=time_intervals,
            metrics=["node_count", "edge_count", "density", "centrality"],
            reference_node_id=self.ml_paper
        )
        
        # Verify structure of results
        self.assertIn("snapshots", results)
        self.assertIn("trends", results)
        self.assertIn("reference_node_metrics", results)
        
        # Should have two snapshots (one for each time interval)
        self.assertEqual(len(results["snapshots"]), 2)
        
        # First snapshot should have AI and ML papers
        early_snapshot = results["snapshots"][0]
        self.assertEqual(early_snapshot["node_count"], 2)  # AI and ML papers
        
        # Second snapshot should have DL, CV and DB papers
        recent_snapshot = results["snapshots"][1]
        self.assertEqual(recent_snapshot["node_count"], 3)  # DL, CV and DB papers
        
        # Reference node (ML paper) should be in first snapshot only
        ref_metrics = results["reference_node_metrics"]
        self.assertEqual(len(ref_metrics), 2)
        self.assertTrue(ref_metrics[0]["present"])    # Present in 2018-2019
        self.assertFalse(ref_metrics[1]["present"])   # Not present in 2020-2022
        
        # Try with node filters
        filtered_results = self.dataset.temporal_graph_analysis(
            time_property="year",
            time_intervals=time_intervals,
            node_filters=[("title", "contains", "Learning")],  # Only Learning papers
            metrics=["node_count"]
        )
        
        # Should only count papers with "Learning" in title
        self.assertLessEqual(filtered_results["snapshots"][0]["node_count"], early_snapshot["node_count"])
        self.assertLessEqual(filtered_results["snapshots"][1]["node_count"], recent_snapshot["node_count"])

    def test_knowledge_graph_completion(self):
        """Test predicting missing edges in the knowledge graph"""
        # First ensure we have enough edges for pattern detection
        # Add some more citation edges
        if not self.dataset.has_edge(self.cv_paper, "cites", self.dl_paper):
            self.dataset.add_edge(self.cv_paper, "cites", self.dl_paper, {"importance": "high"})
        if not self.dataset.has_edge(self.dl_paper, "cites", self.ml_paper):
            self.dataset.add_edge(self.dl_paper, "cites", self.ml_paper, {"importance": "medium"})
        if not self.dataset.has_edge(self.dl_paper, "cites", self.ai_paper):
            self.dataset.add_edge(self.dl_paper, "cites", self.ai_paper, {"importance": "high"})
        if not self.dataset.has_edge(self.ml_paper, "cites", self.ai_paper):
            self.dataset.add_edge(self.ml_paper, "cites", self.ai_paper, {"importance": "high"})
            
        # Test semantic prediction method
        semantic_results = self.dataset.knowledge_graph_completion(
            completion_method="semantic",
            target_relation_types=["cites"],
            min_confidence=0.1,  # Low threshold to ensure results
            max_candidates=10
        )
        
        # Verify result structure
        if semantic_results:  # May not predict anything in simple test graph
            for result in semantic_results:
                self.assertIn("source_node", result)
                self.assertIn("target_node", result)
                self.assertIn("relation_type", result)
                self.assertIn("confidence", result)
                self.assertIn("explanation", result)
                self.assertEqual(result["relation_type"], "cites")
                self.assertGreaterEqual(result["confidence"], 0.1)
                self.assertEqual(result["method"], "semantic")
        
        # Test structural prediction method
        structural_results = self.dataset.knowledge_graph_completion(
            completion_method="structural",
            target_relation_types=["cites"],
            min_confidence=0.1,  # Low threshold to ensure results
            max_candidates=10
        )
        
        # Verify result structure
        if structural_results:  # May not predict anything in simple test graph
            for result in structural_results:
                self.assertIn("source_node", result)
                self.assertIn("target_node", result)
                self.assertIn("relation_type", result)
                self.assertIn("confidence", result)
                self.assertIn("explanation", result)
                self.assertEqual(result["relation_type"], "cites")
                self.assertGreaterEqual(result["confidence"], 0.1)
                self.assertEqual(result["method"], "structural")
        
        # Test combined prediction method
        combined_results = self.dataset.knowledge_graph_completion(
            completion_method="combined",
            target_relation_types=["cites"],
            min_confidence=0.1,  # Low threshold to ensure results
            max_candidates=10,
            use_existing_edges_as_training=True
        )
        
        # Combined method should have model evaluation metrics
        if combined_results:
            for result in combined_results:
                self.assertIn("model_precision", result)
                self.assertIn("model_recall", result)
                self.assertIn("model_f1", result)
                
                # Values should be valid metrics
                self.assertGreaterEqual(result["model_precision"], 0.0)
                self.assertLessEqual(result["model_precision"], 1.0)
                self.assertGreaterEqual(result["model_recall"], 0.0)
                self.assertLessEqual(result["model_recall"], 1.0)

    def test_cross_modal_linking(self):
        """Test creating semantic links between text and image nodes"""
        # Create text nodes for testing
        article1 = self.dataset.add_node("text", {"title": "Introduction to AI", "description": "Overview of artificial intelligence concepts"}, 
                                      vector=np.array([0.9, 0.1, 0.0, 0.0]))
        article2 = self.dataset.add_node("text", {"title": "Computer Vision", "description": "Image recognition techniques"}, 
                                      vector=np.array([0.5, 0.2, 0.9, 0.0]))
        
        # Create image nodes for testing
        image1 = self.dataset.add_node("image", {"alt_text": "Neural network diagram", "date": "2021-05-01"}, 
                                    vector=np.array([0.8, 0.2, 0.1, 0.0]))
        image2 = self.dataset.add_node("image", {"alt_text": "Computer vision example", "date": "2022-01-15"}, 
                                    vector=np.array([0.4, 0.3, 0.9, 0.0]))
        
        # Test embedding-based linking
        links = self.dataset.cross_modal_linking(
            text_nodes=[article1, article2],
            image_nodes=[image1, image2],
            linking_method="embedding",
            min_confidence=0.6,
            attributes_to_transfer=["date"]
        )
        
        # Should create some links
        self.assertGreater(len(links), 0)
        
        # Check link structure
        for link in links:
            self.assertIn("source_node", link)
            self.assertIn("target_node", link)
            self.assertIn("edge_type", link)
            self.assertIn("confidence", link)
            self.assertEqual(link["method"], "embedding")
            
            # Source should be text, target should be image
            self.assertEqual(link["source_node"].type, "text")
            self.assertEqual(link["target_node"].type, "image")
            
            # Should have created edges in the graph
            source_id = link["source_node"].id
            target_id = link["target_node"].id
            edge_type = link["edge_type"]
            self.assertTrue(self.dataset.has_edge(source_id, edge_type, target_id))
        
        # Test metadata-based linking
        metadata_links = self.dataset.cross_modal_linking(
            text_nodes=[article1, article2],
            image_nodes=[image1, image2],
            linking_method="metadata",
            min_confidence=0.1  # Lower threshold for testing
        )
        
        # Verify there are metadata links
        for link in metadata_links:
            if link["method"] == "metadata":
                self.assertGreaterEqual(link["confidence"], 0.1)
                break
    
    def test_schema_based_validation(self):
        """Test validating and fixing graph data based on schemas"""
        # Add paper nodes with schema violations for testing
        invalid_paper = self.dataset.add_node("paper", {
            # Missing required title
            "year": "2020",  # Year as string instead of number
            "citation_count": -5  # Negative citation count (invalid)
        })
        
        # Define test schemas
        node_schemas = {
            "paper": {
                "title": {"type": "string", "required": True},
                "year": {"type": "number", "min": 1900, "max": 2030},
                "citation_count": {"type": "number", "min": 0}
            }
        }
        
        edge_schemas = {
            "cites": {
                "importance": {"type": "string", "enum": ["high", "medium", "low"]},
                "section": {"type": "string"}
            }
        }
        
        # Validate without fixing
        validation = self.dataset.schema_based_validation(
            node_schemas=node_schemas,
            edge_schemas=edge_schemas,
            fix_violations=False
        )
        
        # Should detect violations
        self.assertFalse(validation["valid"])
        self.assertIn(invalid_paper, validation["node_violations"])
        
        # Now validate with fixing
        fixed_validation = self.dataset.schema_based_validation(
            node_schemas=node_schemas,
            edge_schemas=edge_schemas,
            fix_violations=True
        )
        
        # Should have fixed some violations
        self.assertGreater(fixed_validation["fixed_violations"], 0)
        
        # Check that year was converted to number
        self.assertIsInstance(self.dataset.nodes[invalid_paper].data.get("year"), (int, float))
        
        # Citation count should now be valid (at least 0)
        self.assertGreaterEqual(self.dataset.nodes[invalid_paper].data.get("citation_count", 0), 0)
    
    def test_hierarchical_path_search(self):
        """Test hierarchical path search through concept hierarchies"""
        # Set up more comprehensive concept hierarchy
        ai_concept = self.dataset.add_node("concept", {"name": "Artificial Intelligence"}, 
                                           vector=np.array([0.9, 0.1, 0.0, 0.0]))
        ml_concept = self.dataset.add_node("concept", {"name": "Machine Learning"}, 
                                          vector=np.array([0.8, 0.2, 0.0, 0.0]))
        dl_concept = self.dataset.add_node("concept", {"name": "Deep Learning"}, 
                                          vector=np.array([0.7, 0.2, 0.2, 0.0]))
        
        # Add concept relationships
        self.dataset.add_edge(ml_concept, "part_of", ai_concept, {"strength": 0.9})
        self.dataset.add_edge(dl_concept, "part_of", ml_concept, {"strength": 0.8})
        
        # Add connections to papers
        self.dataset.add_edge(self.ai_paper, "about", ai_concept, {"centrality": "primary"})
        self.dataset.add_edge(self.ml_paper, "about", ml_concept, {"centrality": "primary"})
        self.dataset.add_edge(self.dl_paper, "about", dl_concept, {"centrality": "primary"})
        
        # Search for relevant paths
        query_vector = np.array([0.8, 0.2, 0.1, 0.0])  # Similar to ML concept
        
        paths = self.dataset.hierarchical_path_search(
            query_vector=query_vector,
            target_node_types=["paper"],
            guidance_properties={"centrality": 1.0, "strength": 0.8}
        )
        
        # Should find paths
        self.assertGreater(len(paths), 0)
        
        # Check structure of results
        for path in paths:
            self.assertIn("path", path)
            self.assertIn("transitions", path)
            self.assertIn("overall_score", path)
            self.assertIn("semantic_score", path)
            self.assertIn("structural_score", path)
            self.assertIn("end_node", path)
            
            # The end node should be a paper
            self.assertEqual(path["end_node"].type, "paper")
            
            # Path should be valid
            self.assertEqual(len(path["transitions"]), len(path["path"]) - 1)
            
        # Test with invalid query vector
        with self.assertRaises(ValueError):
            self.dataset.hierarchical_path_search(
                query_vector=np.array([0.5]),  # Wrong dimension
                target_node_types=["paper"]
            )
            
    def test_cross_document_reasoning(self):
        """Test reasoning across multiple documents in the graph"""
        # Set up our test graph with document nodes and connecting entities
        
        # 1. Create some document nodes
        doc1 = self.dataset.add_node("document", {
            "title": "Introduction to Machine Learning",
            "content": "Machine learning is a field of AI that focuses on algorithms that learn from data.",
            "year": 2019,
            "author": "Alice Smith"
        }, vector=np.array([0.9, 0.2, 0.1, 0.0]))
        
        doc2 = self.dataset.add_node("document", {
            "title": "Neural Networks in Computer Vision",
            "content": "Computer vision applications often use neural networks for image recognition.",
            "year": 2020,
            "author": "Bob Johnson"
        }, vector=np.array([0.6, 0.2, 0.8, 0.0]))
        
        doc3 = self.dataset.add_node("document", {
            "title": "Reinforcement Learning Applications",
            "content": "Reinforcement learning is used in robotics and game playing scenarios.",
            "year": 2021,
            "author": "Charlie Davis"
        }, vector=np.array([0.7, 0.5, 0.3, 0.0]))
        
        # 2. Create concept entities to connect the documents
        ml_concept = self.dataset.add_node("concept", {
            "name": "Machine Learning",
            "definition": "Field of AI focused on algorithms that improve through experience"
        }, vector=np.array([0.9, 0.3, 0.1, 0.0]))
        
        nn_concept = self.dataset.add_node("concept", {
            "name": "Neural Networks",
            "definition": "Computing systems inspired by biological neural networks"
        }, vector=np.array([0.8, 0.2, 0.5, 0.0]))
        
        rl_concept = self.dataset.add_node("concept", {
            "name": "Reinforcement Learning",
            "definition": "Training agents through reward and punishment"
        }, vector=np.array([0.7, 0.6, 0.2, 0.0]))
        
        # 3. Create relationships between documents and concepts
        self.dataset.add_edge(doc1, "about", ml_concept, {"centrality": "primary", "importance": "high"})
        self.dataset.add_edge(doc1, "mentions", nn_concept, {"centrality": "secondary", "importance": "medium"})
        
        self.dataset.add_edge(doc2, "about", nn_concept, {"centrality": "primary", "importance": "high"})
        self.dataset.add_edge(doc2, "mentions", ml_concept, {"centrality": "secondary", "importance": "medium"})
        
        self.dataset.add_edge(doc3, "about", rl_concept, {"centrality": "primary", "importance": "high"})
        self.dataset.add_edge(doc3, "mentions", ml_concept, {"centrality": "secondary", "importance": "low"})
        
        # 4. Create relationships between concepts
        self.dataset.add_edge(nn_concept, "part_of", ml_concept, {"strength": 0.8})
        self.dataset.add_edge(rl_concept, "part_of", ml_concept, {"strength": 0.7})
        
        # Now run cross_document_reasoning with different depths
        basic_result = self.dataset.cross_document_reasoning(
            query="How are neural networks used in machine learning?",
            document_node_types=["document"],
            reasoning_depth="basic"
        )
        
        # Verify basic results structure
        self.assertIn("answer", basic_result)
        self.assertIn("documents", basic_result)
        self.assertIn("evidence_paths", basic_result)
        self.assertIn("confidence", basic_result)
        self.assertIn("reasoning_trace", basic_result)
        
        # Confidence should be a float between 0 and 1
        self.assertIsInstance(basic_result["confidence"], float)
        self.assertGreaterEqual(basic_result["confidence"], 0.0)
        self.assertLessEqual(basic_result["confidence"], 1.0)
        
        # Should find at least one evidence path
        self.assertGreaterEqual(len(basic_result["evidence_paths"]), 1)
        
        # Try with moderate reasoning depth
        moderate_result = self.dataset.cross_document_reasoning(
            query="What is the relationship between neural networks and reinforcement learning?",
            document_node_types=["document"],
            reasoning_depth="moderate"
        )
        
        # For deep reasoning, create more complex relationships
        author1 = self.dataset.add_node("person", {"name": "Alice Smith", "affiliation": "Stanford"})
        author2 = self.dataset.add_node("person", {"name": "Bob Johnson", "affiliation": "MIT"})
        
        self.dataset.add_edge(doc1, "authored_by", author1)
        self.dataset.add_edge(doc2, "authored_by", author2)
        self.dataset.add_edge(author1, "expert_in", ml_concept, {"level": "high"})
        self.dataset.add_edge(author2, "expert_in", nn_concept, {"level": "high"})
        
        deep_result = self.dataset.cross_document_reasoning(
            query="How do experts in neural networks build upon foundational machine learning concepts?",
            document_node_types=["document"],
            max_hops=3,
            reasoning_depth="deep"
        )
        
        # Deep reasoning should generate more complex inferences
        self.assertGreaterEqual(len(deep_result["reasoning_trace"]), len(basic_result["reasoning_trace"]))
        
        # Test with missing document types
        with self.assertRaises(ValueError):
            self.dataset.cross_document_reasoning(
                query="Test query",
                document_node_types=["non_existent_type"],
                reasoning_depth="basic"
            )

if __name__ == '__main__':
    unittest.main()