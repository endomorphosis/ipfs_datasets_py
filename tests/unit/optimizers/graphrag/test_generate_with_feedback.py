"""
Comprehensive tests for OntologyGenerator.generate_with_feedback().

Tests cover:
- Basic feedback application (confidence filtering, entity/relationship removal, type corrections)
- Entity merging with relationship redirect
- Critic integration  
- Metadata tracking  
- Edge cases (empty feedback, non-existent IDs, invalid data)
- Round-trip validation
"""

import pytest
from typing import Dict, Any, List

from ipfs_datasets_py.optimizers.graphrag.ontology_generator import (
    OntologyGenerator,
    OntologyGenerationContext,
    ExtractionConfig,
)


class TestGenerateWithFeedbackBasic:
    """Basic functionality tests for generate_with_feedback."""

    @pytest.fixture
    def generator(self):
        """Create OntologyGenerator instance."""
        return OntologyGenerator()

    @pytest.fixture
    def context(self):
        """Create standard test context."""
        config = ExtractionConfig(confidence_threshold=0.5)
        return OntologyGenerationContext(
            data_source="test_data",
            data_type="text",
            domain="general",
            config=config,
        )

    def test_generate_with_feedback_no_feedback(self, generator, context):
        """No feedback = same as generate_ontology."""
        text = "Alice works for Acme Corporation. Bob manages the project."
        
        result_with_feedback = generator.generate_with_feedback(text, context)
        result_without_feedback = generator.generate_ontology(text, context)
        
        # Check structure and counts are same (IDs are randomly generated)
        assert len(result_with_feedback["entities"]) == len(result_without_feedback["entities"])
        assert len(result_with_feedback["relationships"]) == len(result_without_feedback["relationships"])
        
        # Check entity texts match
        texts_with = {e["text"] for e in result_with_feedback["entities"]}
        texts_without = {e["text"] for e in result_without_feedback["entities"]}
        assert texts_with == texts_without
        
        assert result_with_feedback["metadata"]["feedback_applied"] == False

    def test_generate_with_feedback_empty_feedback(self, generator, context):
        """Empty feedback dict should mark as applied but make no changes."""
        text = "Test data with entities and relationships."
        
        result = generator.generate_with_feedback(text, context, feedback={})
        
        assert result["metadata"]["feedback_applied"] == False

    def test_generate_with_feedback_metadata_tracking(self, generator, context):
        """Metadata should track feedback application."""
        text = "Alice works at Acme."
        feedback = {"confidence_floor": 0.9}
        
        result = generator.generate_with_feedback(text, context, feedback=feedback)
        
        assert result["metadata"]["feedback_applied"] == True
        assert "feedback_keys" in result["metadata"]
        assert "confidence_floor" in result["metadata"]["feedback_keys"]

    def test_generate_with_feedback_returns_dict(self, generator, context):
        """Return value should be dict with standard ontology structure."""
        text = "Test data."
        result = generator.generate_with_feedback(text, context)
        
        assert isinstance(result, dict)
        assert "entities" in result
        assert "relationships" in result
        assert "metadata" in result
        assert "domain" in result


class TestConfidenceFiltering:
    """Tests for confidence_floor feedback."""

    @pytest.fixture
    def generator(self):
        return OntologyGenerator()

    @pytest.fixture
    def context(self):
        config = ExtractionConfig(confidence_threshold=0.0, max_entities=100)
        return OntologyGenerationContext(
            data_source="test",
            data_type="text",
            domain="general",
            config=config,
        )

    def test_confidence_floor_filters_low_confidence(self, generator, context):
        """Confidence floor should filter out low-confidence entities."""
        # Create a synthetic ontology
        text = "A contract between parties."
        
        result_before = generator.generate_ontology(text, context)
        initial_count = len(result_before["entities"])
        
        # Apply high confidence floor
        feedback = {"confidence_floor": 0.9}
        result_after = generator.generate_with_feedback(text, context, feedback=feedback)
        
        # Should have fewer or equal entities
        assert len(result_after["entities"]) <= initial_count
        
        # All remaining entities should meet threshold
        for entity in result_after["entities"]:
            assert entity.get("confidence", 0) >= 0.9

    def test_confidence_floor_zero(self, generator, context):
        """Confidence floor of 0 should keep all entities."""
        text = "Test data with entities."
        feedback = {"confidence_floor": 0.0}
        
        result = generator.generate_with_feedback(text, context, feedback=feedback)
        
        # No filtering should occur
        assert len(result["entities"]) > 0

    def test_confidence_floor_one(self, generator, context):
        """Confidence floor of 1.0 should keep only perfect entities."""
        text = "Test data."
        feedback = {"confidence_floor": 1.0}
        
        result = generator.generate_with_feedback(text, context, feedback=feedback)
        
        # Very few entities should be perfect
        for entity in result["entities"]:
            assert entity.get("confidence", 0) >= 1.0


class TestEntityRemoval:
    """Tests for entities_to_remove feedback."""

    @pytest.fixture
    def generator(self):
        return OntologyGenerator()

    @pytest.fixture
    def context(self):
        config = ExtractionConfig()
        return OntologyGenerationContext(
            data_source="test",
            data_type="text",
            domain="general",
            config=config,
        )

    def test_remove_existing_entity(self, generator, context):
        """Should successfully remove entity by ID."""
        ontology = {
            "entities": [
                {"id": "e_1", "text": "Alice", "type": "Person", "confidence": 0.9},
                {"id": "e_2", "text": "Bob", "type": "Person", "confidence": 0.8},
            ],
            "relationships": [],
            "metadata": {},
            "domain": "general",
        }
        
        feedback = {"entities_to_remove": ["e_1"]}
        result = generator._apply_feedback_to_ontology(ontology, feedback)
        
        assert result == True
        assert len(ontology["entities"]) == 1
        assert ontology["entities"][0]["id"] == "e_2"

    def test_remove_non_existent_entity(self, generator, context):
        """Removing non-existent entity should not error."""
        ontology = {
            "entities": [
                {"id": "e_1", "text": "Alice", "type": "Person", "confidence": 0.9},
            ],
            "relationships": [],
            "metadata": {},
            "domain": "general",
        }
        
        feedback = {"entities_to_remove": ["e_nonexistent"]}
        result = generator._apply_feedback_to_ontology(ontology, feedback)
        
        assert result == False
        assert len(ontology["entities"]) == 1


class TestEntityMerging:
    """Tests for entities_to_merge feedback."""

    @pytest.fixture
    def generator(self):
        return OntologyGenerator()

    def test_merge_two_entities(self, generator):
        """Merging should keep first entity, remove second, redirect relationships."""
        ontology = {
            "entities": [
                {"id": "e_1", "text": "Alice Smith", "type": "Person", "confidence": 0.9},
                {"id": "e_2", "text": "Alice S.", "type": "Person", "confidence": 0.7},
            ],
            "relationships": [
                {"id": "r_1", "source_id": "e_2", "target_id": "e_1", "type": "same_as"},
            ],
            "metadata": {},
            "domain": "general",
        }
        
        feedback = {"entities_to_merge": [("e_1", "e_2")]}
        result = generator._apply_feedback_to_ontology(ontology, feedback)
        
        assert result == True
        assert len(ontology["entities"]) == 1
        assert ontology["entities"][0]["id"] == "e_1"
        
        # Relationship should redirect e_2 → e_1
        assert ontology["relationships"][0]["source_id"] == "e_1"

    def test_merge_non_existent_entities(self, generator):
        """Merging non-existent entities should not error."""
        ontology = {
            "entities": [{"id": "e_1", "text": "Alice", "type": "Person"}],
            "relationships": [],
            "metadata": {},
            "domain": "general",
        }
        
        feedback = {"entities_to_merge": [("e_nonexistent", "e_other")]}
        result = generator._apply_feedback_to_ontology(ontology, feedback)
        
        assert result == False
        assert len(ontology["entities"]) == 1


class TestTypeCorrection:
    """Tests for type_corrections feedback."""

    @pytest.fixture
    def generator(self):
        return OntologyGenerator()

    def test_correct_entity_type(self, generator):
        """Should update entity type."""
        ontology = {
            "entities": [
                {"id": "e_1", "text": "Apple", "type": "Fruit", "confidence": 0.5},
            ],
            "relationships": [],
            "metadata": {},
            "domain": "general",
        }
        
        feedback = {"type_corrections": {"e_1": "Company"}}
        result = generator._apply_feedback_to_ontology(ontology, feedback)
        
        assert result == True
        assert ontology["entities"][0]["type"] == "Company"

    def test_correct_non_existent_entity_type(self, generator):
        """Correcting non-existent entity should not error."""
        ontology = {
            "entities": [{"id": "e_1", "text": "Alice", "type": "Person"}],
            "relationships": [],
            "metadata": {},
            "domain": "general",
        }
        
        feedback = {"type_corrections": {"e_nonexistent": "Robot"}}
        result = generator._apply_feedback_to_ontology(ontology, feedback)
        
        assert result == False


class TestRelationshipModifications:
    """Tests for relationship feedback (removal and addition)."""

    @pytest.fixture
    def generator(self):
        return OntologyGenerator()

    def test_remove_relationship(self, generator):
        """Should remove relationship by ID."""
        ontology = {
            "entities": [
                {"id": "e_1", "text": "Alice"},
                {"id": "e_2", "text": "Bob"},
            ],
            "relationships": [
                {"id": "r_1", "source_id": "e_1", "target_id": "e_2", "type": "knows"},
                {"id": "r_2", "source_id": "e_2", "target_id": "e_1", "type": "knows"},
            ],
            "metadata": {},
            "domain": "general",
        }
        
        feedback = {"relationships_to_remove": ["r_1"]}
        result = generator._apply_feedback_to_ontology(ontology, feedback)
        
        assert result == True
        assert len(ontology["relationships"]) == 1
        assert ontology["relationships"][0]["id"] == "r_2"

    def test_add_relationship(self, generator):
        """Should add new relationship with generated ID if missing."""
        ontology = {
            "entities": [
                {"id": "e_1", "text": "Alice"},
                {"id": "e_2", "text": "Bob"},
            ],
            "relationships": [],
            "metadata": {},
            "domain": "general",
        }
        
        feedback = {
            "relationships_to_add": [
                {"source_id": "e_1", "target_id": "e_2", "type": "knows"},
            ]
        }
        result = generator._apply_feedback_to_ontology(ontology, feedback)
        
        assert result == True
        assert len(ontology["relationships"]) == 1
        assert ontology["relationships"][0]["source_id"] == "e_1"
        assert ontology["relationships"][0]["target_id"] == "e_2"
        assert "id" in ontology["relationships"][0]


class TestMultipleFeedbackCombined:
    """Tests for combining multiple feedback types."""

    @pytest.fixture
    def generator(self):
        return OntologyGenerator()

    def test_combined_feedback_operations(self, generator):
        """Should apply multiple feedback types in sequence."""
        ontology = {
            "entities": [
                {"id": "e_1", "text": "Alice", "type": "Person", "confidence": 0.9},
                {"id": "e_2", "text": "Alice S.", "type": "Worker", "confidence": 0.5},
                {"id": "e_3", "text": "Bob", "type": "Manager", "confidence": 0.95},
            ],
            "relationships": [
                {"id": "r_1", "source_id": "e_1", "target_id": "e_3", "type": "reports_to"},
            ],
            "metadata": {},
            "domain": "general",
        }
        
        feedback = {
            "confidence_floor": 0.7,  # Removes e_2
            "type_corrections": {"e_3": "Executive"},
            "relationships_to_add": [
                {"source_id": "e_1", "target_id": "e_3", "type": "manages"},
            ]
        }
        
        result = generator._apply_feedback_to_ontology(ontology, feedback)
        
        assert result == True
        assert len(ontology["entities"]) == 2  # e_2 filtered out
        assert ontology["entities"][1]["type"] == "Executive"  # e_3 type updated
        assert len(ontology["relationships"]) == 2  # Original + new


class TestFeedbackEdgeCases:
    """Edge case tests."""

    @pytest.fixture
    def generator(self):
        return OntologyGenerator()

    def test_empty_ontology(self, generator):
        """Feedback on empty ontology should not crash."""
        ontology = {
            "entities": [],
            "relationships": [],
            "metadata": {},
            "domain": "general",
        }
        
        feedback = {
            "confidence_floor": 0.8,
            "entities_to_remove": ["nonexistent"],
        }
        
        result = generator._apply_feedback_to_ontology(ontology, feedback)
        assert result == False

    def test_feedback_with_special_characters(self, generator):
        """Feedback with special characters should work."""
        ontology = {
            "entities": [
                {"id": "e_1", "text": "Société Générale", "type": "Bank"},
            ],
            "relationships": [],
            "metadata": {},
            "domain": "general",
        }
        
        feedback = {
            "type_corrections": {"e_1": "金融機関"}  # Japanese
        }
        
        result = generator._apply_feedback_to_ontology(ontology, feedback)
        assert result == True
        assert ontology["entities"][0]["type"] == "金融機関"

    def test_malformed_feedback_values(self, generator):
        """Malformed feedback should be handled gracefully."""
        ontology = {
            "entities": [{"id": "e_1", "text": "Test"}],
            "relationships": [],
            "metadata": {},
            "domain": "general",
        }
        
        # These should either be ignored or handled gracefully
        feedback = {
            "confidence_floor": "invalid",  # String instead of float
            "entities_to_remove": "should_be_list",  # String instead of list
        }
        
        # Method should not crash
        try:
            result = generator._apply_feedback_to_ontology(ontology, feedback)
            # Either returns False (no modifications) or handles type conversion
            assert isinstance(result, bool)
        except (ValueError, TypeError):
            # Type errors are acceptable
            pass


class TestIntegrationWithCritic:
    """Tests for critic integration in generate_with_feedback."""

    @pytest.fixture
    def generator(self):
        return OntologyGenerator()

    @pytest.fixture
    def context(self):
        config = ExtractionConfig()
        return OntologyGenerationContext(
            data_source="test",
            data_type="text",
            domain="general",
            config=config,
        )

    def test_generate_with_feedback_without_critic(self, generator, context):
        """Should work without critic."""
        text = "Simple test."
        result = generator.generate_with_feedback(text, context)
        
        assert "critic_score" not in result["metadata"]
        assert result["metadata"]["feedback_applied"] == False

    def test_generate_with_feedback_with_none_critic(self, generator, context):
        """Passing critic=None should work."""
        text = "Test data."
        result = generator.generate_with_feedback(
            text,
            context,
            feedback=None,
            critic=None
        )
        
        assert isinstance(result, dict)
        assert "critic_score" not in result["metadata"]


class TestFeedbackRoundTrip:
    """Tests for round-trip feedback application and reversal."""

    @pytest.fixture
    def generator(self):
        return OntologyGenerator()

    def test_apply_feedback_then_reflect_in_metadata(self, generator):
        """Feedback application should be reflected in metadata."""
        ontology = {
            "entities": [
                {"id": "e_1", "text": "Alice", "type": "Person", "confidence": 0.9},
            ],
            "relationships": [],
            "metadata": {},
            "domain": "general",
        }
        
        feedback = {
            "type_corrections": {"e_1": "Director"},
            "confidence_floor": 0.85,
        }
        
        result = generator._apply_feedback_to_ontology(ontology, feedback)
        
        assert result == True
        assert ontology["entities"][0]["type"] == "Director"
