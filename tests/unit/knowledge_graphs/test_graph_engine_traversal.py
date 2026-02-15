"""
Tests for GraphEngine Traversal Implementation (Phase 1, Task 1.1)

This test suite validates the newly implemented graph traversal capabilities:
- get_relationships() - Find relationships by node
- traverse_pattern() - Pattern matching for MATCH clauses
- find_paths() - Path finding between nodes

Tests follow GIVEN-WHEN-THEN format per repository standards.
"""

import pytest
from ipfs_datasets_py.knowledge_graphs.core.query_executor import GraphEngine
from ipfs_datasets_py.knowledge_graphs.neo4j_compat.types import Node, Relationship


class TestGraphEngineTraversal:
    """Test suite for GraphEngine traversal methods."""
    
    @pytest.fixture
    def graph_engine(self):
        """Create a GraphEngine instance for testing."""
        return GraphEngine()
    
    @pytest.fixture
    def sample_graph(self, graph_engine):
        """
        Create a sample graph for testing:
        
        (Alice:Person)-[:KNOWS]->(Bob:Person)-[:KNOWS]->(Charlie:Person)
                |                                            |
                +------------------[:KNOWS]-----------------+
        """
        # Create nodes
        alice = graph_engine.create_node(
            labels=["Person"],
            properties={"name": "Alice", "age": 30}
        )
        bob = graph_engine.create_node(
            labels=["Person"],
            properties={"name": "Bob", "age": 25}
        )
        charlie = graph_engine.create_node(
            labels=["Person"],
            properties={"name": "Charlie", "age": 35}
        )
        
        # Create relationships
        rel1 = graph_engine.create_relationship("KNOWS", alice.id, bob.id)
        rel2 = graph_engine.create_relationship("KNOWS", bob.id, charlie.id)
        rel3 = graph_engine.create_relationship("KNOWS", alice.id, charlie.id)
        
        return {
            "nodes": {"alice": alice, "bob": bob, "charlie": charlie},
            "relationships": {"rel1": rel1, "rel2": rel2, "rel3": rel3}
        }
    
    def test_get_relationships_outgoing(self, graph_engine, sample_graph):
        """
        GIVEN: A graph with nodes and relationships
        WHEN: Getting outgoing relationships for a node
        THEN: Returns only outgoing relationships
        """
        # GIVEN
        alice = sample_graph["nodes"]["alice"]
        
        # WHEN
        rels = graph_engine.get_relationships(alice.id, direction="out")
        
        # THEN
        assert len(rels) == 2  # Alice knows Bob and Charlie
        assert all(rel._start_node == alice.id for rel in rels)
    
    def test_get_relationships_incoming(self, graph_engine, sample_graph):
        """
        GIVEN: A graph with nodes and relationships
        WHEN: Getting incoming relationships for a node
        THEN: Returns only incoming relationships
        """
        # GIVEN
        charlie = sample_graph["nodes"]["charlie"]
        
        # WHEN
        rels = graph_engine.get_relationships(charlie.id, direction="in")
        
        # THEN
        assert len(rels) == 2  # Bob and Alice know Charlie
        assert all(rel._end_node == charlie.id for rel in rels)
    
    def test_get_relationships_both(self, graph_engine, sample_graph):
        """
        GIVEN: A graph with nodes and relationships
        WHEN: Getting all relationships for a node
        THEN: Returns both incoming and outgoing relationships
        """
        # GIVEN
        bob = sample_graph["nodes"]["bob"]
        
        # WHEN
        rels = graph_engine.get_relationships(bob.id, direction="both")
        
        # THEN
        assert len(rels) == 2  # Bob has 1 incoming (from Alice) and 1 outgoing (to Charlie)
    
    def test_get_relationships_by_type(self, graph_engine, sample_graph):
        """
        GIVEN: A graph with multiple relationship types
        WHEN: Filtering relationships by type
        THEN: Returns only matching relationships
        """
        # GIVEN
        alice = sample_graph["nodes"]["alice"]
        bob = sample_graph["nodes"]["bob"]
        
        # Add a WORKS_WITH relationship
        graph_engine.create_relationship("WORKS_WITH", alice.id, bob.id)
        
        # WHEN
        knows_rels = graph_engine.get_relationships(alice.id, "out", "KNOWS")
        works_rels = graph_engine.get_relationships(alice.id, "out", "WORKS_WITH")
        
        # THEN
        assert len(knows_rels) == 2  # Alice KNOWS Bob and Charlie
        assert len(works_rels) == 1  # Alice WORKS_WITH Bob
        assert all(rel._type == "KNOWS" for rel in knows_rels)
        assert all(rel._type == "WORKS_WITH" for rel in works_rels)
    
    def test_traverse_pattern_single_hop(self, graph_engine, sample_graph):
        """
        GIVEN: A graph with relationships
        WHEN: Traversing a single-hop pattern
        THEN: Returns matching node-relationship-node patterns
        """
        # GIVEN
        alice = sample_graph["nodes"]["alice"]
        pattern = [
            {"variable": "n", "labels": ["Person"]},
            {"rel_type": "KNOWS", "direction": "out", "variable": "r"},
            {"variable": "f", "labels": ["Person"]}
        ]
        
        # WHEN
        matches = graph_engine.traverse_pattern([alice], pattern)
        
        # THEN
        assert len(matches) == 2  # Alice knows 2 people
        for match in matches:
            assert "n" in match or "start" in match
            assert "r" in match  # Has relationship
            assert "f" in match  # Has friend node
    
    def test_traverse_pattern_two_hops(self, graph_engine, sample_graph):
        """
        GIVEN: A graph with multi-hop paths
        WHEN: Traversing a two-hop pattern
        THEN: Returns matching two-hop patterns
        """
        # GIVEN
        alice = sample_graph["nodes"]["alice"]
        pattern = [
            {"variable": "start", "labels": ["Person"]},
            {"rel_type": "KNOWS", "direction": "out", "variable": "r1"},
            {"variable": "middle", "labels": ["Person"]},
            {"rel_type": "KNOWS", "direction": "out", "variable": "r2"},
            {"variable": "end", "labels": ["Person"]}
        ]
        
        # WHEN
        matches = graph_engine.traverse_pattern([alice], pattern)
        
        # THEN
        # Alice -> Bob -> Charlie is one two-hop path
        assert len(matches) >= 1
        for match in matches:
            assert "r1" in match
            assert "r2" in match
            assert "middle" in match
            assert "end" in match
    
    def test_find_paths_direct(self, graph_engine, sample_graph):
        """
        GIVEN: Two directly connected nodes
        WHEN: Finding paths between them
        THEN: Returns the direct path
        """
        # GIVEN
        alice = sample_graph["nodes"]["alice"]
        bob = sample_graph["nodes"]["bob"]
        
        # WHEN
        paths = graph_engine.find_paths(alice.id, bob.id)
        
        # THEN
        assert len(paths) >= 1
        assert len(paths[0]) == 1  # Direct path has 1 relationship
    
    def test_find_paths_two_hop(self, graph_engine, sample_graph):
        """
        GIVEN: Nodes connected via intermediate node
        WHEN: Finding paths between them
        THEN: Returns both direct and indirect paths
        """
        # GIVEN
        alice = sample_graph["nodes"]["alice"]
        charlie = sample_graph["nodes"]["charlie"]
        
        # WHEN
        paths = graph_engine.find_paths(alice.id, charlie.id, max_depth=3)
        
        # THEN
        assert len(paths) >= 2  # Direct path + indirect via Bob
        
        # Should have both 1-hop and 2-hop paths
        path_lengths = [len(path) for path in paths]
        assert 1 in path_lengths  # Direct path
        assert 2 in path_lengths  # Via Bob
    
    def test_find_paths_no_path(self, graph_engine, sample_graph):
        """
        GIVEN: Two unconnected nodes
        WHEN: Finding paths between them
        THEN: Returns empty list
        """
        # GIVEN
        alice = sample_graph["nodes"]["alice"]
        
        # Create disconnected node
        david = graph_engine.create_node(
            labels=["Person"],
            properties={"name": "David", "age": 40}
        )
        
        # WHEN
        paths = graph_engine.find_paths(alice.id, david.id)
        
        # THEN
        assert len(paths) == 0
    
    def test_find_paths_with_cycle_detection(self, graph_engine, sample_graph):
        """
        GIVEN: A graph with cycles
        WHEN: Finding paths
        THEN: Does not get stuck in infinite loop (cycle detection works)
        """
        # GIVEN - Add cycle: Charlie -> Alice
        charlie = sample_graph["nodes"]["charlie"]
        alice = sample_graph["nodes"]["alice"]
        graph_engine.create_relationship("KNOWS", charlie.id, alice.id)
        
        # WHEN
        paths = graph_engine.find_paths(alice.id, charlie.id, max_depth=10)
        
        # THEN
        # Should complete without infinite loop
        assert len(paths) > 0
        # All paths should respect max_depth
        for path in paths:
            assert len(path) <= 10
    
    def test_get_relationships_empty_graph(self, graph_engine):
        """
        GIVEN: An empty graph
        WHEN: Getting relationships for non-existent node
        THEN: Returns empty list
        """
        # WHEN
        rels = graph_engine.get_relationships("non-existent-id")
        
        # THEN
        assert len(rels) == 0
    
    def test_traverse_pattern_with_limit(self, graph_engine, sample_graph):
        """
        GIVEN: A graph with multiple matches
        WHEN: Traversing pattern with limit
        THEN: Returns only up to limit results
        """
        # GIVEN
        alice = sample_graph["nodes"]["alice"]
        pattern = [
            {"variable": "n", "labels": ["Person"]},
            {"rel_type": "KNOWS", "direction": "out", "variable": "r"},
            {"variable": "f", "labels": ["Person"]}
        ]
        
        # WHEN
        matches = graph_engine.traverse_pattern([alice], pattern, limit=1)
        
        # THEN
        assert len(matches) == 1


class TestGraphEngineIntegration:
    """Integration tests for GraphEngine with QueryExecutor."""
    
    @pytest.fixture
    def graph_engine(self):
        """Create a GraphEngine instance."""
        return GraphEngine()
    
    def test_create_and_query_graph(self, graph_engine):
        """
        GIVEN: An empty graph engine
        WHEN: Creating nodes and querying them
        THEN: Can create and retrieve nodes successfully
        """
        # GIVEN & WHEN
        node1 = graph_engine.create_node(
            labels=["Person"],
            properties={"name": "Alice", "age": 30}
        )
        node2 = graph_engine.create_node(
            labels=["Person"],
            properties={"name": "Bob", "age": 25}
        )
        rel = graph_engine.create_relationship("KNOWS", node1.id, node2.id)
        
        # THEN
        assert graph_engine.get_node(node1.id) is not None
        assert graph_engine.get_node(node2.id) is not None
        assert len(graph_engine.get_relationships(node1.id)) == 1
    
    def test_find_nodes_with_labels(self, graph_engine):
        """
        GIVEN: A graph with mixed node types
        WHEN: Finding nodes by label
        THEN: Returns only matching nodes
        """
        # GIVEN
        person1 = graph_engine.create_node(
            labels=["Person"],
            properties={"name": "Alice"}
        )
        person2 = graph_engine.create_node(
            labels=["Person"],
            properties={"name": "Bob"}
        )
        company = graph_engine.create_node(
            labels=["Company"],
            properties={"name": "Acme Corp"}
        )
        
        # WHEN
        persons = graph_engine.find_nodes(labels=["Person"])
        companies = graph_engine.find_nodes(labels=["Company"])
        
        # THEN
        assert len(persons) == 2
        assert len(companies) == 1
        assert all("Person" in node.labels for node in persons)
        assert all("Company" in node.labels for node in companies)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
