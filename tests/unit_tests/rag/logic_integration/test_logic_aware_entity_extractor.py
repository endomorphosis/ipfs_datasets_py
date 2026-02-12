"""Tests for logic-aware entity extractor.

This module tests the extraction of logical entities from text,
including agents, obligations, permissions, prohibitions, temporal
constraints, and conditionals.
"""

import pytest
from ipfs_datasets_py.rag.logic_integration.logic_aware_entity_extractor import (
    LogicAwareEntityExtractor,
    LogicalEntity,
    LogicalEntityType,
    LogicalRelationship
)


class TestLogicAwareEntityExtractor:
    """Test logic-aware entity extraction."""
    
    @pytest.fixture
    def extractor(self):
        """Create entity extractor instance."""
        return LogicAwareEntityExtractor(use_neural=False)
    
    def test_extract_agents(self, extractor):
        """GIVEN: Text with agent names
        WHEN: Extracting entities
        THEN: Agents should be correctly identified
        """
        text = "Alice must pay Bob within 30 days. Company X shall deliver to Organization Y."
        entities = extractor.extract_entities(text)
        
        agents = [e for e in entities if e.entity_type == LogicalEntityType.AGENT]
        agent_names = [a.text for a in agents]
        
        assert len(agents) >= 2
        assert "Alice" in agent_names
        assert "Bob" in agent_names
    
    def test_extract_obligations(self, extractor):
        """GIVEN: Text with obligations
        WHEN: Extracting entities
        THEN: Obligations should be correctly identified
        """
        text = "Alice must pay the fee. Bob shall deliver goods. Carol is required to notify."
        entities = extractor.extract_entities(text)
        
        obligations = [e for e in entities if e.entity_type == LogicalEntityType.OBLIGATION]
        
        assert len(obligations) >= 3
        assert any("must pay" in o.text.lower() for o in obligations)
        assert any("shall deliver" in o.text.lower() for o in obligations)
        assert any("required to" in o.text.lower() for o in obligations)
        assert all(o.confidence >= 0.75 for o in obligations)
    
    def test_extract_permissions(self, extractor):
        """GIVEN: Text with permissions
        WHEN: Extracting entities
        THEN: Permissions should be correctly identified
        """
        text = "Users may access the system. Members can modify settings. Staff are allowed to view reports."
        entities = extractor.extract_entities(text)
        
        permissions = [e for e in entities if e.entity_type == LogicalEntityType.PERMISSION]
        
        assert len(permissions) >= 3
        assert any("may access" in p.text.lower() for p in permissions)
        assert any("can modify" in p.text.lower() for p in permissions)
        assert any("allowed to" in p.text.lower() for p in permissions)
    
    def test_extract_prohibitions(self, extractor):
        """GIVEN: Text with prohibitions
        WHEN: Extracting entities
        THEN: Prohibitions should be correctly identified
        """
        text = "Users must not share credentials. Staff shall not disclose information. Forbidden to access."
        entities = extractor.extract_entities(text)
        
        prohibitions = [e for e in entities if e.entity_type == LogicalEntityType.PROHIBITION]
        
        assert len(prohibitions) >= 3
        assert any("must not" in p.text.lower() for p in prohibitions)
        assert any("shall not" in p.text.lower() for p in prohibitions)
        assert any("forbidden" in p.text.lower() for p in prohibitions)
        assert all(p.confidence >= 0.75 for p in prohibitions)
    
    def test_extract_temporal_constraints(self, extractor):
        """GIVEN: Text with temporal constraints
        WHEN: Extracting entities
        THEN: Temporal constraints should be correctly identified
        """
        text = "Payment must be made within 30 days. Delivery is required after 7 days. Always verify. Never delay."
        entities = extractor.extract_entities(text)
        
        temporal = [e for e in entities if e.entity_type == LogicalEntityType.TEMPORAL_CONSTRAINT]
        
        assert len(temporal) >= 4
        assert any("within" in t.text.lower() for t in temporal)
        assert any("after" in t.text.lower() for t in temporal)
        assert any("always" in t.text.lower() for t in temporal)
        assert any("never" in t.text.lower() for t in temporal)
    
    def test_extract_conditionals(self, extractor):
        """GIVEN: Text with conditional statements
        WHEN: Extracting entities
        THEN: Conditionals should be correctly identified
        """
        text = "If payment is received then goods will be shipped. When contract expires, terminate service."
        entities = extractor.extract_entities(text)
        
        conditionals = [e for e in entities if e.entity_type == LogicalEntityType.CONDITIONAL]
        
        assert len(conditionals) >= 1
        assert any("if" in c.text.lower() and "then" in c.text.lower() for c in conditionals)
    
    def test_extract_relationships(self, extractor):
        """GIVEN: Text with related entities
        WHEN: Extracting relationships
        THEN: Relationships should be correctly identified
        """
        text = "Alice must pay Bob within 30 days."
        entities = extractor.extract_entities(text)
        relationships = extractor.extract_relationships(text, entities)
        
        assert len(relationships) >= 1
        
        # Check relationship types
        rel_types = [r.relation_type for r in relationships]
        assert any(rt in ['must_do', 'interacts_with', 'constrained_by'] for rt in rel_types)
    
    def test_confidence_scores(self, extractor):
        """GIVEN: Extracted entities
        WHEN: Checking confidence scores
        THEN: All confidence scores should be in valid range [0, 1]
        """
        text = "Alice must pay Bob. Carol may access the system."
        entities = extractor.extract_entities(text)
        
        for entity in entities:
            assert 0.0 <= entity.confidence <= 1.0
    
    def test_metadata_positions(self, extractor):
        """GIVEN: Extracted entities
        WHEN: Checking metadata
        THEN: Entities should have position information
        """
        text = "Alice must pay Bob"
        entities = extractor.extract_entities(text)
        
        for entity in entities:
            assert 'position' in entity.metadata
            pos = entity.metadata['position']
            assert isinstance(pos, tuple)
            assert len(pos) == 2
            assert pos[0] <= pos[1]
    
    def test_empty_text(self, extractor):
        """GIVEN: Empty text
        WHEN: Extracting entities
        THEN: Should return empty list without error
        """
        entities = extractor.extract_entities("")
        assert entities == []
    
    def test_complex_legal_text(self, extractor):
        """GIVEN: Complex legal text with multiple entity types
        WHEN: Extracting entities
        THEN: Should extract all entity types correctly
        """
        text = """
        Service Agreement
        
        The Provider must deliver services within 14 business days.
        The Client shall pay fees within 30 days of invoice.
        Either party may terminate with 90 days notice.
        Provider must not disclose confidential information.
        If payment is late, then interest accrues immediately.
        Services shall always meet quality standards.
        """
        
        entities = extractor.extract_entities(text)
        
        # Should have multiple types
        entity_types = {e.entity_type for e in entities}
        assert LogicalEntityType.AGENT in entity_types
        assert LogicalEntityType.OBLIGATION in entity_types
        assert LogicalEntityType.PERMISSION in entity_types or LogicalEntityType.PROHIBITION in entity_types
        
        # Should have reasonable number of entities
        assert len(entities) >= 5
    
    def test_infer_relationship_types(self, extractor):
        """GIVEN: Different entity type combinations
        WHEN: Inferring relationships
        THEN: Should return correct relationship types
        """
        agent1 = LogicalEntity("Alice", LogicalEntityType.AGENT, 0.9)
        agent2 = LogicalEntity("Bob", LogicalEntityType.AGENT, 0.9)
        obligation = LogicalEntity("must pay", LogicalEntityType.OBLIGATION, 0.85)
        temporal = LogicalEntity("within 30 days", LogicalEntityType.TEMPORAL_CONSTRAINT, 0.85)
        
        # Agent + Obligation = must_do
        rel_type = extractor._infer_relationship_type(agent1, obligation)
        assert rel_type == "must_do"
        
        # Obligation + Temporal = constrained_by
        rel_type = extractor._infer_relationship_type(obligation, temporal)
        assert rel_type == "constrained_by"
        
        # Agent + Agent = interacts_with
        rel_type = extractor._infer_relationship_type(agent1, agent2)
        assert rel_type == "interacts_with"
    
    def test_entity_validation(self):
        """GIVEN: Entity with invalid confidence
        WHEN: Creating entity
        THEN: Should raise ValueError
        """
        with pytest.raises(ValueError):
            LogicalEntity("Test", LogicalEntityType.AGENT, 1.5)
        
        with pytest.raises(ValueError):
            LogicalEntity("Test", LogicalEntityType.AGENT, -0.1)
    
    def test_relationship_validation(self):
        """GIVEN: Relationship with invalid confidence
        WHEN: Creating relationship
        THEN: Should raise ValueError
        """
        entity1 = LogicalEntity("Alice", LogicalEntityType.AGENT, 0.9)
        entity2 = LogicalEntity("Bob", LogicalEntityType.AGENT, 0.9)
        
        with pytest.raises(ValueError):
            LogicalRelationship(entity1, entity2, "test", 1.5)
        
        with pytest.raises(ValueError):
            LogicalRelationship(entity1, entity2, "test", -0.1)


class TestLogicalEntityTypes:
    """Test logical entity type enumeration."""
    
    def test_all_entity_types_defined(self):
        """GIVEN: LogicalEntityType enum
        WHEN: Checking available types
        THEN: Should have all 7 types defined
        """
        expected_types = {
            'AGENT', 'PREDICATE', 'OBLIGATION', 'PERMISSION',
            'PROHIBITION', 'TEMPORAL_CONSTRAINT', 'CONDITIONAL'
        }
        
        actual_types = {t.name for t in LogicalEntityType}
        assert expected_types == actual_types
    
    def test_entity_type_values(self):
        """GIVEN: LogicalEntityType enum
        WHEN: Checking values
        THEN: Values should be lowercase strings
        """
        for entity_type in LogicalEntityType:
            assert isinstance(entity_type.value, str)
            assert entity_type.value.islower()
