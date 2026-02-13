"""Tests for logic-aware knowledge graph.

This module tests the knowledge graph construction, consistency checking,
and query capabilities.
"""

import pytest
from ipfs_datasets_py.rag.logic_integration.logic_aware_entity_extractor import (
    LogicalEntity,
    LogicalEntityType,
    LogicalRelationship
)
from ipfs_datasets_py.rag.logic_integration.logic_aware_knowledge_graph import (
    LogicAwareKnowledgeGraph,
    LogicNode,
    LogicEdge
)


class TestLogicAwareKnowledgeGraph:
    """Test logic-aware knowledge graph."""
    
    @pytest.fixture
    def kg(self):
        """Create knowledge graph instance."""
        return LogicAwareKnowledgeGraph()
    
    @pytest.fixture
    def sample_entities(self):
        """Create sample entities for testing."""
        return [
            LogicalEntity("Alice", LogicalEntityType.AGENT, 0.9),
            LogicalEntity("Bob", LogicalEntityType.AGENT, 0.9),
            LogicalEntity("must pay", LogicalEntityType.OBLIGATION, 0.85),
            LogicalEntity("within 30 days", LogicalEntityType.TEMPORAL_CONSTRAINT, 0.85),
            LogicalEntity("may access", LogicalEntityType.PERMISSION, 0.8)
        ]
    
    def test_add_node(self, kg):
        """GIVEN: A knowledge graph and an entity
        WHEN: Adding a node
        THEN: Node should be added with unique ID
        """
        entity = LogicalEntity("Alice", LogicalEntityType.AGENT, 0.9)
        node_id = kg.add_node(entity)
        
        assert node_id in kg.nodes
        assert kg.nodes[node_id].entity == entity
        assert node_id.startswith("agent_")
    
    def test_add_multiple_nodes(self, kg, sample_entities):
        """GIVEN: Multiple entities
        WHEN: Adding nodes
        THEN: All nodes should be added with unique IDs
        """
        node_ids = [kg.add_node(entity) for entity in sample_entities]
        
        assert len(node_ids) == len(sample_entities)
        assert len(set(node_ids)) == len(node_ids)  # All unique
        assert len(kg.nodes) == len(sample_entities)
    
    def test_add_edge(self, kg):
        """GIVEN: Two entities and a relationship
        WHEN: Adding an edge
        THEN: Edge should be created between nodes
        """
        entity1 = LogicalEntity("Alice", LogicalEntityType.AGENT, 0.9)
        entity2 = LogicalEntity("must pay", LogicalEntityType.OBLIGATION, 0.85)
        
        relationship = LogicalRelationship(
            entity1, entity2, "must_do", 0.85
        )
        
        kg.add_edge(relationship)
        
        assert len(kg.edges) == 1
        assert len(kg.nodes) == 2  # Both nodes created
    
    def test_find_or_create_node(self, kg):
        """GIVEN: An entity already in the graph
        WHEN: Adding same entity again
        THEN: Should return existing node ID
        """
        entity = LogicalEntity("Alice", LogicalEntityType.AGENT, 0.9)
        
        node_id1 = kg.add_node(entity)
        node_id2 = kg._find_or_create_node(entity)
        
        assert node_id1 == node_id2
        assert len(kg.nodes) == 1
    
    def test_add_theorem(self, kg):
        """GIVEN: A theorem formula
        WHEN: Adding theorem
        THEN: Theorem should be stored
        """
        kg.add_theorem("modus_ponens", "P -> Q, P |- Q", proven=True)
        
        assert "modus_ponens" in kg.theorems
        assert kg.theorems["modus_ponens"] == "P -> Q, P |- Q"
    
    def test_check_consistency_clean_graph(self, kg):
        """GIVEN: A consistent knowledge graph
        WHEN: Checking consistency
        THEN: Should return True with no inconsistencies
        """
        entity1 = LogicalEntity("Alice", LogicalEntityType.AGENT, 0.9)
        entity2 = LogicalEntity("must pay", LogicalEntityType.OBLIGATION, 0.85)
        
        kg.add_node(entity1)
        kg.add_node(entity2)
        
        is_consistent, inconsistencies = kg.check_consistency()
        
        assert is_consistent
        assert len(inconsistencies) == 0
    
    def test_check_consistency_contradictory_obligations(self, kg):
        """GIVEN: Contradictory obligations
        WHEN: Checking consistency
        THEN: Should detect inconsistency
        """
        obl1 = LogicalEntity("must pay", LogicalEntityType.OBLIGATION, 0.85)
        obl2 = LogicalEntity("must not pay", LogicalEntityType.OBLIGATION, 0.85)
        
        kg.add_node(obl1)
        kg.add_node(obl2)
        
        is_consistent, inconsistencies = kg.check_consistency()
        
        assert not is_consistent
        assert len(inconsistencies) > 0
        assert "contradictory" in inconsistencies[0].lower()
    
    def test_check_consistency_obligation_prohibition_conflict(self, kg):
        """GIVEN: Conflicting obligation and prohibition
        WHEN: Checking consistency
        THEN: Should detect conflict
        """
        obl = LogicalEntity("must share", LogicalEntityType.OBLIGATION, 0.85)
        proh = LogicalEntity("must not share", LogicalEntityType.PROHIBITION, 0.85)
        
        kg.add_node(obl)
        kg.add_node(proh)
        
        is_consistent, inconsistencies = kg.check_consistency()
        
        assert not is_consistent
        assert len(inconsistencies) > 0
        assert "conflict" in inconsistencies[0].lower()
    
    def test_check_temporal_consistency(self, kg):
        """GIVEN: Conflicting temporal constraints
        WHEN: Checking consistency
        THEN: Should detect temporal conflict
        """
        always = LogicalEntity("always verify", LogicalEntityType.TEMPORAL_CONSTRAINT, 0.85)
        never = LogicalEntity("never verify", LogicalEntityType.TEMPORAL_CONSTRAINT, 0.85)
        
        kg.add_node(always)
        kg.add_node(never)
        
        is_consistent, inconsistencies = kg.check_consistency()
        
        assert not is_consistent
        assert any("temporal" in inc.lower() for inc in inconsistencies)
    
    def test_query_keyword_match(self, kg):
        """GIVEN: Knowledge graph with nodes
        WHEN: Querying with keywords
        THEN: Should return matching nodes
        """
        entities = [
            LogicalEntity("Alice must pay", LogicalEntityType.OBLIGATION, 0.85),
            LogicalEntity("Bob must deliver", LogicalEntityType.OBLIGATION, 0.85),
            LogicalEntity("Carol may access", LogicalEntityType.PERMISSION, 0.8)
        ]
        
        for entity in entities:
            kg.add_node(entity)
        
        results = kg.query("pay")
        
        assert len(results) >= 1
        assert any("pay" in node.entity.text.lower() for node in results)
    
    def test_query_top_k(self, kg):
        """GIVEN: Knowledge graph with many nodes
        WHEN: Querying with top_k limit
        THEN: Should return at most top_k results
        """
        for i in range(20):
            entity = LogicalEntity(f"Entity {i} with test", LogicalEntityType.AGENT, 0.9)
            kg.add_node(entity)
        
        results = kg.query("test", top_k=5)
        
        assert len(results) <= 5
    
    def test_get_related_theorems(self, kg):
        """GIVEN: Knowledge graph with theorems
        WHEN: Getting related theorems for a node
        THEN: Should return theorems with matching keywords
        """
        entity = LogicalEntity("Alice must pay", LogicalEntityType.OBLIGATION, 0.85)
        node_id = kg.add_node(entity)
        
        kg.add_theorem("payment_rule", "pay(X) -> obligated(X)")
        kg.add_theorem("delivery_rule", "deliver(X) -> required(X)")
        
        related = kg.get_related_theorems(node_id)
        
        assert len(related) >= 1
        assert any("pay" in str(formula).lower() for _, formula in related)
    
    def test_export_to_dict(self, kg, sample_entities):
        """GIVEN: Knowledge graph with nodes and edges
        WHEN: Exporting to dictionary
        THEN: Should return complete graph representation
        """
        for entity in sample_entities[:3]:
            kg.add_node(entity)
        
        relationship = LogicalRelationship(
            sample_entities[0], sample_entities[2], "must_do", 0.85
        )
        kg.add_edge(relationship)
        
        kg.add_theorem("test_theorem", "P -> Q")
        
        export = kg.export_to_dict()
        
        assert 'nodes' in export
        assert 'edges' in export
        assert 'theorems' in export
        assert len(export['nodes']) >= 3
        assert len(export['edges']) >= 1
        assert len(export['theorems']) >= 1
    
    def test_get_stats(self, kg, sample_entities):
        """GIVEN: Knowledge graph with various entity types
        WHEN: Getting statistics
        THEN: Should return accurate counts
        """
        for entity in sample_entities:
            kg.add_node(entity)
        
        kg.add_theorem("test_theorem", "P -> Q")
        
        stats = kg.get_stats()
        
        assert stats['nodes'] == len(sample_entities)
        assert stats['agents'] == 2
        assert stats['obligations'] == 1
        assert stats['permissions'] == 1
        assert stats['theorems'] == 1
    
    def test_empty_query(self, kg):
        """GIVEN: Empty knowledge graph
        WHEN: Querying
        THEN: Should return empty list
        """
        results = kg.query("anything")
        assert results == []
    
    def test_graph_without_networkx(self):
        """GIVEN: System without NetworkX
        WHEN: Creating knowledge graph
        THEN: Should work in limited mode
        """
        # This tests graceful degradation
        kg = LogicAwareKnowledgeGraph()
        entity = LogicalEntity("Test", LogicalEntityType.AGENT, 0.9)
        
        node_id = kg.add_node(entity)
        assert node_id in kg.nodes
    
    def test_complex_graph_operations(self, kg):
        """GIVEN: Complex knowledge graph with multiple entity types
        WHEN: Performing various operations
        THEN: All operations should work correctly
        """
        # Add various entities
        alice = LogicalEntity("Alice", LogicalEntityType.AGENT, 0.9)
        bob = LogicalEntity("Bob", LogicalEntityType.AGENT, 0.9)
        pay_obl = LogicalEntity("must pay", LogicalEntityType.OBLIGATION, 0.85)
        deliver_obl = LogicalEntity("shall deliver", LogicalEntityType.OBLIGATION, 0.85)
        temporal = LogicalEntity("within 30 days", LogicalEntityType.TEMPORAL_CONSTRAINT, 0.85)
        
        alice_id = kg.add_node(alice)
        bob_id = kg.add_node(bob)
        pay_id = kg.add_node(pay_obl)
        deliver_id = kg.add_node(deliver_obl)
        temporal_id = kg.add_node(temporal)
        
        # Add relationships
        rel1 = LogicalRelationship(alice, pay_obl, "must_do", 0.85)
        rel2 = LogicalRelationship(bob, deliver_obl, "must_do", 0.85)
        rel3 = LogicalRelationship(pay_obl, temporal, "constrained_by", 0.8)
        
        kg.add_edge(rel1)
        kg.add_edge(rel2)
        kg.add_edge(rel3)
        
        # Add theorems
        kg.add_theorem("payment_theorem", "pay(X) -> owes(X)")
        kg.add_theorem("delivery_theorem", "deliver(X) -> ships(X)")
        
        # Check state
        assert len(kg.nodes) == 5
        assert len(kg.edges) == 3
        assert len(kg.theorems) == 2
        
        # Query
        results = kg.query("pay")
        assert len(results) >= 1
        
        # Check consistency
        is_consistent, _ = kg.check_consistency()
        assert is_consistent
        
        # Get stats
        stats = kg.get_stats()
        assert stats['nodes'] == 5
        assert stats['edges'] == 3
        assert stats['theorems'] == 2


class TestLogicNodeEdge:
    """Test LogicNode and LogicEdge data classes."""
    
    def test_logic_node_creation(self):
        """GIVEN: Entity and metadata
        WHEN: Creating LogicNode
        THEN: Node should be created with all attributes
        """
        entity = LogicalEntity("Alice", LogicalEntityType.AGENT, 0.9)
        node = LogicNode(id="agent_0", entity=entity)
        
        assert node.id == "agent_0"
        assert node.entity == entity
        assert node.proven is False
        assert isinstance(node.metadata, dict)
        assert node.created_at is not None
    
    def test_logic_edge_creation(self):
        """GIVEN: Source, target, and relationship
        WHEN: Creating LogicEdge
        THEN: Edge should be created with all attributes
        """
        entity1 = LogicalEntity("Alice", LogicalEntityType.AGENT, 0.9)
        entity2 = LogicalEntity("Bob", LogicalEntityType.AGENT, 0.9)
        relationship = LogicalRelationship(entity1, entity2, "interacts_with", 0.8)
        
        edge = LogicEdge(
            source_id="agent_0",
            target_id="agent_1",
            relationship=relationship,
            confidence=0.8
        )
        
        assert edge.source_id == "agent_0"
        assert edge.target_id == "agent_1"
        assert edge.relationship == relationship
        assert edge.confidence == 0.8
