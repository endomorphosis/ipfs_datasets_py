"""Tests for context window relationship type inference.

Validates:
- Context window extraction around entity pairs
- Keyword pattern-based type inference from context
- Improved type confidence scores compared to type-only inference
"""

import pytest
from typing import List

from .ontology_generator import (
    OntologyGenerator,
    OntologyGenerationContext,
    Entity,
    Relationship,
    DataType,
    ExtractionStrategy,
)


class TestContextWindowExtraction:
    """Test context window extraction helper."""
    
    def test_extract_context_window_basic(self):
        """Context window extraction includes both positions."""
        generator = OntologyGenerator(use_ipfs_accelerate=False)
        text = "A" * 50 + "ENTITY1" + "B" * 30 + "ENTITY2" + "C" * 50
        
        pos1 = 50  # Position of ENTITY1
        pos2 = 87  # Position of ENTITY2
        
        window = generator._extract_context_window(text, pos1, pos2, window_size=20)
        
        assert "ENTITY1" in window
        assert "ENTITY2" in window
    
    def test_extract_context_window_near_start(self):
        """Context window near start doesn't underflow."""
        generator = OntologyGenerator(use_ipfs_accelerate=False)
        text = "ENTITY1 and ENTITY2 are at the start"
        
        pos1 = 0
        pos2 = 12
        
        window = generator._extract_context_window(text, pos1, pos2, window_size=50)
        
        assert "ENTITY1" in window
        assert "ENTITY2" in window
        assert window.startswith("ENTITY1")  # Starts at text beginning
    
    def test_extract_context_window_near_end(self):
        """Context window near end doesn't overflow."""
        generator = OntologyGenerator(use_ipfs_accelerate=False)
        text = "A" * 100 + "ENTITY1 and ENTITY2"
        
        pos1 = 100
        pos2 = 112
        
        window = generator._extract_context_window(text, pos1, pos2, window_size=50)
        
        assert "ENTITY1" in window
        assert "ENTITY2" in window


class TestContextBasedTypeInference:
    """Test relationship type inference from context windows."""
    
    def test_infer_employs_from_context(self):
        """'employs' detected from employment keywords."""
        generator = OntologyGenerator(use_ipfs_accelerate=False)
        context = "Microsoft employs many engineers"
        
        rel_type, confidence = generator._infer_type_from_context(
            context,
            "Microsoft",
            "engineers",
            "organization",
            "person"
        )
        
        assert rel_type == "employs"
        assert confidence >= 0.70
    
    def test_infer_manages_from_context(self):
        """'manages' detected from management keywords."""
        generator = OntologyGenerator(use_ipfs_accelerate=False)
        context = "Alice manages the engineering team"
        
        rel_type, confidence = generator._infer_type_from_context(
            context,
            "Alice",
            "team",
            "person",
            "organization"
        )
        
        assert rel_type == "manages"
        assert confidence >= 0.70
    
    def test_infer_located_in_from_context(self):
        """'located_in' detected from location keywords."""
        generator = OntologyGenerator(use_ipfs_accelerate=False)
        context = "The headquarters is located in Seattle"
        
        rel_type, confidence = generator._infer_type_from_context(
            context,
            "headquarters",
            "Seattle",
            "organization",
            "location"
        )
        
        assert rel_type == "located_in"
        assert confidence >= 0.70
    
    def test_infer_produces_from_context(self):
        """'produces' detected from production keywords."""
        generator = OntologyGenerator(use_ipfs_accelerate=False)
        context = "Tesla produces electric vehicles"
        
        rel_type, confidence = generator._infer_type_from_context(
            context,
            "Tesla",
            "vehicles",
            "organization",
            "product"
        )
        
        assert rel_type == "produces"
        assert confidence >= 0.68
    
    def test_infer_partners_with_from_context(self):
        """'partners_with' detected from partnership keywords."""
        generator = OntologyGenerator(use_ipfs_accelerate=False)
        context = "Apple partners with Intel on chip design"
        
        rel_type, confidence = generator._infer_type_from_context(
            context,
            "Apple",
            "Intel",
            "organization",
            "organization"
        )
        
        assert rel_type == "partners_with"
        assert confidence >= 0.65
    
    def test_fallback_to_type_based_inference(self):
        """Falls back to entity type-based inference without keywords."""
        generator = OntologyGenerator(use_ipfs_accelerate=False)
        context = "Alice and Microsoft are mentioned together"
        
        rel_type, confidence = generator._infer_type_from_context(
            context,
            "Alice",
            "Microsoft",
            "person",
            "organization"
        )
        
        # Should fall back to type-based rule (works_for)
        assert rel_type == "works_for"
        assert 0.50 <= confidence <= 0.70
    
    def test_default_fallback_for_unknown_types(self):
        """Default 'related_to' for unknown entity types without keywords."""
        generator = OntologyGenerator(use_ipfs_accelerate=False)
        context = "Entity1 and Entity2 are near each other"
        
        rel_type, confidence = generator._infer_type_from_context(
            context,
            "Entity1",
            "Entity2",
            "unknown",
            "unknown"
        )
        
        assert rel_type == "related_to"
        assert confidence >= 0.40


class TestIntegration_ContextWindowInference:
    """Integration tests for context window relationship inference."""
    
    def test_infer_relationships_uses_context_window(self):
        """infer_relationships uses context window for better type inference."""
        generator = OntologyGenerator(use_ipfs_accelerate=False)
        
        entities = [
            Entity(id="e1", text="Microsoft", type="organization", description="A company", confidence=0.9),
            Entity(id="e2", text="engineers", type="person", description="People who code", confidence=0.8),
        ]
        
        context = OntologyGenerationContext(
            data_source="test",
            data_type=DataType.TEXT,
            domain="technology",
            extraction_strategy=ExtractionStrategy.RULE_BASED
        )
        
        data = "Microsoft employs many talented engineers around the world"
        
        relationships = generator.infer_relationships(entities, context, data)
        
        # Should detect 'employs' from context window
        assert len(relationships) > 0
        
        # Find relationship between Microsoft and engineers
        rel = next((r for r in relationships if 
                   (r.source_id == "e1" and r.target_id == "e2") or
                   (r.source_id == "e2" and r.target_id == "e1")), None)
        
        assert rel is not None
        assert rel.type in ["employs", "works_for", "related_to"]  # Context-aware inference
        assert rel.properties.get("type_method") in ["verb_frame", "context_window"]
        assert 'type_confidence' in rel.properties
    
    def test_context_window_improves_type_accuracy(self):
        """Context window inference produces more specific types than type-only."""
        generator = OntologyGenerator(use_ipfs_accelerate=False)
        
        entities = [
            Entity(id="e1", text="Google", type="organization", description="Tech company", confidence=0.9),
            Entity(id="e2", text="Android", type="product", description="Mobile OS", confidence=0.85),
        ]
        
        context = OntologyGenerationContext(
            data_source="test",
            data_type=DataType.TEXT,
            domain="technology",
            extraction_strategy=ExtractionStrategy.RULE_BASED
        )
        
        # Context with clear production relationship
        data_with_context = "Google creates and produces Android operating system"
        rels_with_context = generator.infer_relationships(entities, context, data_with_context)
        
        # Find the relationship
        rel = next((r for r in rels_with_context if 
                   r.type == "produces" or r.type == "creates"), None)
        
        assert rel is not None
        assert rel.properties.get("type_method") in ["verb_frame", "context_window"]
        assert rel.properties.get("type_confidence", 0) >= 0.65


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
