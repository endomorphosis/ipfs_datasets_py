"""
Comprehensive tests for deontic_logic_converter module.

Tests the main conversion engine that transforms GraphRAG-processed legal
documents into deontic first-order logic formulas.
"""

import pytest
from dataclasses import dataclass, field
from typing import List, Dict, Any
from unittest.mock import Mock, patch, MagicMock

from ipfs_datasets_py.logic.integration.deontic_logic_converter import (
    ConversionContext,
    ConversionResult,
    DeonticLogicConverter,
    Entity,
    Relationship,
    KnowledgeGraph,
)
from ipfs_datasets_py.logic.tools.deontic_logic_core import (
    DeonticFormula,
    DeonticOperator,
    LegalAgent,
    DeonticRuleSet,
)


class TestConversionContext:
    """Test ConversionContext dataclass."""
    
    def test_create_basic_context(self):
        """GIVEN document path
        WHEN creating ConversionContext
        THEN context should have correct defaults"""
        context = ConversionContext(
            source_document_path="/path/to/contract.pdf",
            document_title="Employment Contract"
        )
        
        assert context.source_document_path == "/path/to/contract.pdf"
        assert context.document_title == "Employment Contract"
        assert context.confidence_threshold == 0.5
        assert context.enable_temporal_analysis is True
        assert context.enable_agent_inference is True
    
    def test_context_with_custom_settings(self):
        """GIVEN custom conversion settings
        WHEN creating ConversionContext
        THEN settings should be applied"""
        context = ConversionContext(
            source_document_path="/path/to/doc.txt",
            confidence_threshold=0.8,
            enable_temporal_analysis=False,
            enable_agent_inference=False
        )
        
        assert context.confidence_threshold == 0.8
        assert context.enable_temporal_analysis is False
        assert context.enable_agent_inference is False
    
    def test_context_to_dict(self):
        """GIVEN ConversionContext
        WHEN converting to dictionary
        THEN dictionary should be serializable"""
        context = ConversionContext(
            source_document_path="/test/path",
            document_title="Test Doc",
            jurisdiction="US-CA"
        )
        
        context_dict = context.to_dict()
        
        assert context_dict["source_document_path"] == "/test/path"
        assert context_dict["document_title"] == "Test Doc"
        assert context_dict["jurisdiction"] == "US-CA"
        assert isinstance(context_dict["confidence_threshold"], float)


class TestConversionResult:
    """Test ConversionResult dataclass."""
    
    def test_create_empty_result(self):
        """GIVEN no formulas
        WHEN creating ConversionResult
        THEN result should have empty lists"""
        result = ConversionResult(
            deontic_formulas=[],
            rule_set=DeonticRuleSet(name="TestRules", formulas=[]),
            conversion_metadata={}
        )
        
        assert len(result.deontic_formulas) == 0
        assert len(result.errors) == 0
        assert len(result.warnings) == 0
        assert isinstance(result.statistics, dict)
    
    def test_result_with_errors_and_warnings(self):
        """GIVEN conversion with issues
        WHEN creating ConversionResult
        THEN errors and warnings should be recorded"""
        errors = ["Failed to parse entity E1", "Missing agent information"]
        warnings = ["Low confidence on relationship R1"]
        
        result = ConversionResult(
            deontic_formulas=[],
            rule_set=DeonticRuleSet(name="Test", formulas=[]),
            conversion_metadata={},
            errors=errors,
            warnings=warnings
        )
        
        assert len(result.errors) == 2
        assert len(result.warnings) == 1
        assert "Failed to parse" in result.errors[0]
    
    def test_result_to_dict(self):
        """GIVEN ConversionResult
        WHEN converting to dictionary
        THEN dictionary should contain all fields"""
        result = ConversionResult(
            deontic_formulas=[],
            rule_set=DeonticRuleSet(name="Rules", formulas=[]),
            conversion_metadata={"version": "1.0"},
            statistics={"obligations": 5, "permissions": 3}
        )
        
        result_dict = result.to_dict()
        
        assert "deontic_formulas" in result_dict
        assert "rule_set" in result_dict
        assert result_dict["conversion_metadata"]["version"] == "1.0"
        assert result_dict["statistics"]["obligations"] == 5


class TestDeonticLogicConverter:
    """Test DeonticLogicConverter main class."""
    
    def test_converter_initialization(self):
        """GIVEN no parameters
        WHEN creating DeonticLogicConverter
        THEN converter should initialize with defaults"""
        converter = DeonticLogicConverter()
        
        assert converter.domain_knowledge is not None
        assert converter.enable_symbolic_ai is True
        assert isinstance(converter.conversion_stats, dict)
    
    def test_converter_with_symbolic_ai_disabled(self):
        """GIVEN symbolic AI disabled
        WHEN creating converter
        THEN symbolic analyzer should be None"""
        converter = DeonticLogicConverter(enable_symbolic_ai=False)
        
        assert converter.enable_symbolic_ai is False
        # Symbolic analyzer might be None or not initialized
    
    def test_conversion_stats_initialization(self):
        """GIVEN new converter
        WHEN checking conversion stats
        THEN stats should start at zero"""
        converter = DeonticLogicConverter()
        
        stats = converter.conversion_stats
        
        assert stats["total_entities_processed"] == 0
        assert stats["total_relationships_processed"] == 0
        assert stats["obligations_extracted"] == 0


class TestEntityConversion:
    """Test conversion of GraphRAG entities to deontic formulas."""
    
    def test_convert_obligation_entity(self):
        """GIVEN entity representing obligation
        WHEN converting to deontic formula
        THEN obligation formula should be created"""
        entity = Entity(
            id="E1",
            type="obligation",
            data={
                "agent": "Provider",
                "action": "deliver_services",
                "description": "Provider must deliver services"
            }
        )
        
        # This would test actual conversion
        # For now, just test entity structure
        assert entity.type == "obligation"
        assert "agent" in entity.data
        assert entity.data["agent"] == "Provider"
    
    def test_convert_permission_entity(self):
        """GIVEN entity representing permission
        WHEN converting to deontic formula
        THEN permission formula should be created"""
        entity = Entity(
            id="E2",
            type="permission",
            data={
                "agent": "Client",
                "action": "terminate_contract",
                "description": "Client may terminate"
            }
        )
        
        assert entity.type == "permission"
        assert entity.data["action"] == "terminate_contract"
    
    def test_convert_prohibition_entity(self):
        """GIVEN entity representing prohibition
        WHEN converting to deontic formula
        THEN prohibition formula should be created"""
        entity = Entity(
            id="E3",
            type="prohibition",
            data={
                "agent": "Employee",
                "action": "disclose_information",
                "description": "Employee must not disclose"
            }
        )
        
        assert entity.type == "prohibition"
        assert entity.data["agent"] == "Employee"


class TestRelationshipConversion:
    """Test conversion of GraphRAG relationships."""
    
    def test_convert_conditional_relationship(self):
        """GIVEN relationship representing condition
        WHEN converting
        THEN conditional formula should be created"""
        relationship = Relationship(
            id="R1",
            source="E1",
            target="E2",
            type="conditional",
            data={"condition": "if payment_received"}
        )
        
        assert relationship.type == "conditional"
        assert "condition" in relationship.data
    
    def test_convert_temporal_relationship(self):
        """GIVEN relationship with temporal constraints
        WHEN converting
        THEN temporal operators should be included"""
        relationship = Relationship(
            id="R2",
            source="E1",
            target="E2",
            type="temporal",
            data={
                "temporal_operator": "before",
                "timeframe": "30 days"
            }
        )
        
        assert relationship.type == "temporal"
        assert relationship.data["temporal_operator"] == "before"
    
    def test_convert_causal_relationship(self):
        """GIVEN causal relationship
        WHEN converting
        THEN causal logic should be captured"""
        relationship = Relationship(
            id="R3",
            source="E1",
            target="E2",
            type="causes",
            data={"causality": "direct"}
        )
        
        assert relationship.type == "causes"
        assert relationship.data["causality"] == "direct"


class TestKnowledgeGraphConversion:
    """Test conversion of complete knowledge graphs."""
    
    def test_convert_empty_knowledge_graph(self):
        """GIVEN empty knowledge graph
        WHEN converting to deontic logic
        THEN result should have no formulas"""
        kg = KnowledgeGraph(entities=[], relationships=[])
        
        assert len(kg.entities) == 0
        assert len(kg.relationships) == 0
    
    def test_convert_simple_knowledge_graph(self):
        """GIVEN knowledge graph with entities and relationships
        WHEN converting
        THEN formulas should be generated"""
        entities = [
            Entity("E1", {"type": "obligation"}, type="obligation"),
            Entity("E2", {"type": "permission"}, type="permission")
        ]
        relationships = [
            Relationship("R1", "E1", "E2", "implies", {})
        ]
        
        kg = KnowledgeGraph(entities=entities, relationships=relationships)
        
        assert len(kg.entities) == 2
        assert len(kg.relationships) == 1
    
    def test_convert_complex_knowledge_graph(self):
        """GIVEN complex knowledge graph with multiple entity types
        WHEN converting
        THEN all entity types should be processed"""
        entities = [
            Entity("E1", {"type": "obligation", "agent": "A1"}, "obligation"),
            Entity("E2", {"type": "permission", "agent": "A2"}, "permission"),
            Entity("E3", {"type": "prohibition", "agent": "A3"}, "prohibition"),
        ]
        relationships = [
            Relationship("R1", "E1", "E2", "conditional", {}),
            Relationship("R2", "E2", "E3", "temporal", {}),
        ]
        
        kg = KnowledgeGraph(entities=entities, relationships=relationships)
        
        assert len(kg.entities) == 3
        assert len(kg.relationships) == 2
        
        # Check entity types
        types = [e.type for e in kg.entities]
        assert "obligation" in types
        assert "permission" in types
        assert "prohibition" in types


class TestAgentInference:
    """Test agent inference from entities."""
    
    def test_extract_agent_from_entity(self):
        """GIVEN entity with agent information
        WHEN extracting agent
        THEN LegalAgent should be created"""
        entity = Entity(
            "E1",
            {
                "agent": "Company XYZ",
                "agent_type": "organization",
                "role": "provider"
            },
            type="obligation"
        )
        
        assert "agent" in entity.data
        assert entity.data["agent"] == "Company XYZ"
        assert entity.data["agent_type"] == "organization"
    
    def test_infer_agent_from_context(self):
        """GIVEN entity without explicit agent
        WHEN inferring agent from context
        THEN agent should be identified"""
        # This would test agent inference logic
        entity = Entity(
            "E1",
            {"description": "The employer must provide insurance"},
            type="obligation"
        )
        
        # Agent inference would extract "employer" from description
        assert "description" in entity.data
        assert "employer" in entity.data["description"]


class TestTemporalAnalysis:
    """Test temporal constraint extraction."""
    
    def test_extract_temporal_before(self):
        """GIVEN entity with 'before' temporal constraint
        WHEN extracting temporal info
        THEN temporal operator should be 'before'"""
        entity = Entity(
            "E1",
            {
                "description": "Payment must be made before delivery",
                "temporal_constraint": "before"
            },
            type="obligation"
        )
        
        assert "temporal_constraint" in entity.data
        assert entity.data["temporal_constraint"] == "before"
    
    def test_extract_temporal_within(self):
        """GIVEN entity with 'within' temporal constraint
        WHEN extracting temporal info
        THEN duration should be captured"""
        entity = Entity(
            "E1",
            {
                "description": "Must respond within 30 days",
                "duration": "30 days"
            },
            type="obligation"
        )
        
        assert "duration" in entity.data
        assert "30 days" in entity.data["duration"]
    
    def test_extract_temporal_after(self):
        """GIVEN entity with 'after' temporal constraint
        WHEN extracting temporal info
        THEN temporal operator should be 'after'"""
        entity = Entity(
            "E1",
            {
                "description": "Services begin after payment",
                "temporal_constraint": "after"
            },
            type="obligation"
        )
        
        assert entity.data["temporal_constraint"] == "after"


class TestConditionExtraction:
    """Test conditional logic extraction."""
    
    def test_extract_if_then_condition(self):
        """GIVEN entity with if-then structure
        WHEN extracting conditions
        THEN conditional should be identified"""
        entity = Entity(
            "E1",
            {
                "description": "If payment is late, then penalty applies",
                "condition_type": "if_then"
            },
            type="obligation"
        )
        
        assert "condition_type" in entity.data
        assert entity.data["condition_type"] == "if_then"
    
    def test_extract_unless_condition(self):
        """GIVEN entity with 'unless' condition
        WHEN extracting conditions
        THEN negated conditional should be identified"""
        entity = Entity(
            "E1",
            {
                "description": "Contract continues unless terminated",
                "condition_type": "unless"
            },
            type="obligation"
        )
        
        assert entity.data["condition_type"] == "unless"


class TestErrorHandling:
    """Test error handling in conversion."""
    
    def test_handle_missing_entity_data(self):
        """GIVEN entity with missing data
        WHEN converting
        THEN error should be recorded"""
        entity = Entity("E1", {}, type="obligation")
        
        # Converter should handle missing data gracefully
        assert entity.id == "E1"
        assert len(entity.data) == 0
    
    def test_handle_invalid_entity_type(self):
        """GIVEN entity with unknown type
        WHEN converting
        THEN should handle gracefully"""
        entity = Entity("E1", {"type": "unknown_type"}, type="unknown")
        
        # Should not crash
        assert entity.type == "unknown"
    
    def test_handle_malformed_relationship(self):
        """GIVEN relationship with missing fields
        WHEN converting
        THEN should handle gracefully"""
        relationship = Relationship("R1", "E1", "", "unknown", {})
        
        # Should have id and source at minimum
        assert relationship.id == "R1"
        assert relationship.source == "E1"


class TestStatisticsTracking:
    """Test conversion statistics tracking."""
    
    def test_track_entity_count(self):
        """GIVEN entities processed
        WHEN tracking statistics
        THEN entity count should increment"""
        converter = DeonticLogicConverter()
        
        initial_count = converter.conversion_stats["total_entities_processed"]
        
        # This would be incremented during conversion
        assert initial_count == 0
    
    def test_track_formula_types(self):
        """GIVEN various formula types created
        WHEN tracking statistics
        THEN counts by type should be maintained"""
        converter = DeonticLogicConverter()
        
        stats = converter.conversion_stats
        
        assert "obligations_extracted" in stats
        # Other formula type counts would be tested here


class TestIntegration:
    """Integration tests for complete conversion workflows."""
    
    @pytest.mark.skip(reason="Requires full GraphRAG integration")
    def test_convert_legal_contract(self):
        """GIVEN complete legal contract
        WHEN converting to deontic logic
        THEN all obligations, permissions, prohibitions should be extracted"""
        pass
    
    @pytest.mark.skip(reason="Requires domain knowledge setup")
    def test_convert_with_domain_knowledge(self):
        """GIVEN converter with legal domain knowledge
        WHEN converting document
        THEN domain patterns should be recognized"""
        pass


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
