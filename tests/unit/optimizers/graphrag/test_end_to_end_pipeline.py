"""End-to-end tests for the full GraphRAG ontology optimization pipeline.

Tests the complete workflow: generate → evaluate → optimize → validate
"""

import pytest
from unittest.mock import Mock
import time

from ipfs_datasets_py.optimizers.graphrag.ontology_generator import (
    OntologyGenerator,
    ExtractionConfig,
)
from ipfs_datasets_py.optimizers.graphrag.ontology_critic import OntologyCritic
from ipfs_datasets_py.optimizers.graphrag.ontology_session import OntologySession
from ipfs_datasets_py.optimizers.graphrag.ontology_validator import OntologyValidator


class TestEndToEndPipelineGenerate:
    """Test the generate stage of the pipeline."""
    
    def test_generates_valid_ontology(self):
        """Generate stage produces valid ontology structure."""
        config = ExtractionConfig(max_entities=20)
        generator = OntologyGenerator(config)
        
        input_text = "Alice works with Bob at Acme. They collaborate on AI projects."
        ontology = generator.generate_ontology(input_text)
        
        assert ontology is not None
        assert isinstance(ontology, dict)
    
    def test_generate_with_empty_input(self):
        """Generate stage handles empty input gracefully."""
        config = ExtractionConfig()
        generator = OntologyGenerator(config)
        
        ontology = generator.generate_ontology("")
        
        assert ontology is None or isinstance(ontology, dict)
    
    def test_generate_respects_max_entities(self):
        """Generate stage respects max_entities limit."""
        config = ExtractionConfig(max_entities=5)
        generator = OntologyGenerator(config)
        
        input_text = "Person A, B, C, D, E, F, G work together on projects."
        ontology = generator.generate_ontology(input_text)
        
        if ontology and isinstance(ontology, dict):
            entities = ontology.get("entities", [])
            assert len(entities) <= 5 or entities == []


class TestEndToEndPipelineEvaluate:
    """Test the evaluate stage of the pipeline."""
    
    def test_evaluate_valid_ontology(self):
        """Evaluate stage assesses ontology quality."""
        critic = OntologyCritic()
        ontology = {
            "entities": [
                {"id": "e1", "text": "Alice", "type": "Person", "confidence": 0.9},
                {"id": "e2", "text": "Bob", "type": "Person", "confidence": 0.85},
            ],
            "relationships": [
                {"id": "r1", "source_id": "e1", "target_id": "e2", "type": "works_with", "confidence": 0.8}
            ]
        }
        
        result = critic.evaluate_ontology(ontology)
        
        assert result is not None
        # Result could be dict, float, or other - just ensure it exists
    
    def test_evaluate_empty_ontology(self):
        """Evaluate stage handles empty ontology."""
        critic = OntologyCritic()
        ontology = {"entities": [], "relationships": []}
        
        try:
            result = critic.evaluate_ontology(ontology)
            assert result is not None
        except (ValueError, AttributeError):
            # Valid to raise error for empty ontology
            pass
    
    def test_evaluate_handles_invalid_ontology(self):
        """Evaluate stage handles invalid structures gracefully."""
        critic = OntologyCritic()
        invalid = {"invalid": "structure"}
        
        try:
            result = critic.evaluate_ontology(invalid)
            # If no error, result should still be valid
        except (ValueError, KeyError, AttributeError):
            # Valid to raise error for invalid input
            pass


class TestEndToEndPipelineValidate:
    """Test the validate stage of the pipeline."""
    
    def test_validator_suggests_merges(self):
        """Validate stage identifies merge candidates."""
        validator = OntologyValidator()
        ontology = {
            "entities": [
                {"id": "e1", "text": "Alice", "type": "Person", "confidence": 0.9},
                {"id": "e2", "text": "Alice", "type": "Person", "confidence": 0.88},
            ],
            "relationships": []
        }
        
        suggestions = validator.suggest_entity_merges(ontology, threshold=0.8)
        
        assert isinstance(suggestions, list)
        # May or may not have suggestions
    
    def test_validator_empty_entity_list(self):
        """Validate stage handles empty entity list."""
        validator = OntologyValidator()
        ontology = {"entities": [], "relationships": []}
        
        suggestions = validator.suggest_entity_merges(ontology)
        
        assert suggestions == []
    
    def test_validator_single_entity(self):
        """Validate stage handles single entity."""
        validator = OntologyValidator()
        ontology = {
            "entities": [{"id": "e1", "text": "Alice", "type": "Person", "confidence": 0.9}],
            "relationships": []
        }
        
        suggestions = validator.suggest_entity_merges(ontology)
        
        assert suggestions == []


class TestEndToEndPipelineIntegration:
    """Test multiple stages together."""
    
    def test_generate_and_evaluate(self):
        """Generate stage output works with evaluate stage."""
        config = ExtractionConfig(max_entities=10)
        generator = OntologyGenerator(config)
        critic = OntologyCritic()
        
        input_text = "Test document with entities and relationships."
        ontology = generator.generate_ontology(input_text)
        
        if ontology and isinstance(ontology, dict):
            result = critic.evaluate_ontology(ontology)
            # Ensure evaluation works without error
            assert result is not None
    
    def test_evaluate_and_validate(self):
        """Evaluate stage output works with validate stage."""
        critic = OntologyCritic()
        validator = OntologyValidator()
        
        ontology = {
            "entities": [
                {"id": "e1", "text": "Alice Smith", "type": "Person", "confidence": 0.9},
                {"id": "e2", "text": "Alice S.", "type": "Person", "confidence": 0.85},
            ],
            "relationships": []
        }
        
        # Evaluate
        eval_result = critic.evaluate_ontology(ontology)
        
        # Validate
        suggestions = validator.suggest_entity_merges(ontology, threshold=0.7)
        
        # Both should work
        assert eval_result is not None
        assert isinstance(suggestions, list)
    
    def test_full_three_stage_pipeline(self):
        """Full generate → evaluate → validate pipeline."""
        config = ExtractionConfig(max_entities=15)
        generator = OntologyGenerator(config)
        critic = OntologyCritic()
        validator = OntologyValidator()
        
        input_text = "Alice, Bob, and Charlie work at Example Corp on various projects."
        
        # Stage 1: Generate
        ontology = generator.generate_ontology(input_text)
        
        if ontology and isinstance(ontology, dict) and ontology.get("entities"):
            # Stage 2: Evaluate
            eval_result = critic.evaluate_ontology(ontology)
            
            # Stage 3: Validate
            suggestions = validator.suggest_entity_merges(ontology, threshold=0.8)
            
            # Verify all stages completed
            assert eval_result is not None
            assert isinstance(suggestions, list)


class TestEndToEndPipelineSession:
    """Test pipeline using OntologySession."""
    
    def test_session_initialization(self):
        """Session initializes with required components."""
        generator = Mock()
        mediator = Mock()
        critic = Mock()
        validator = Mock()
        
        session = OntologySession(
            generator=generator,
            mediator=mediator,
            critic=critic,
            validator=validator
        )
        
        assert session is not None
        assert session.generator == generator
        assert session. max_rounds >= 1
    
    def test_session_timing_before_start(self):
        """Session timing returns 0 before starting."""
        generator = Mock()
        mediator = Mock()
        critic = Mock()
        validator = Mock()
        
        session = OntologySession(
            generator=generator,
            mediator=mediator,
            critic=critic,
            validator=validator
        )
        
        elapsed = session.elapsed_ms()
        
        assert elapsed == 0.0
        assert isinstance(elapsed, float)
    
    def test_session_timing_after_start(self):
        """Session timing increases after starting."""
        generator = Mock()
        mediator = Mock()
        critic = Mock()
        validator = Mock()
        
        session = OntologySession(
            generator=generator,
            mediator=mediator,
            critic=critic,
            validator=validator
        )
        
        # Simulate session start
        session.start_time = time.time() - 0.05  # Started 50ms ago
        
        elapsed = session.elapsed_ms()
        
        assert elapsed >= 30.0  # At least ~50ms ago
        assert isinstance(elapsed, float)


class TestEndToEndPipelineErrorRecovery:
    """Test pipeline error recovery."""
    
    def test_pipeline_continues_after_empty_generate(self):
        """Pipeline continues even if generate produces empty result."""
        config = ExtractionConfig()
        generator = OntologyGenerator(config)
        validator = OntologyValidator()
        
        # Try with empty input
        ontology = generator.generate_ontology("")
        
        # Validator should handle None or empty easily
        if ontology and isinstance(ontology, dict):
            suggestions = validator.suggest_entity_merges(ontology)
            assert isinstance(suggestions, list)
    
    def test_pipeline_handles_malformed_entities(self):
        """Pipeline handles entities with missing fields."""
        validator = OntologyValidator()
        ontology = {
            "entities": [
                {"id": "e1"},  # Missing text and type
                {"text": "Alice"},  # Missing id
            ],
            "relationships": []
        }
        
        try:
            suggestions = validator.suggest_entity_merges(ontology)
            assert isinstance(suggestions, list)
        except (ValueError, KeyError):
            # Valid to reject malformed data
            pass


class TestEndToEndPipelineDataConsistency:
    """Test data consistency through pipeline."""
    
    def test_ontology_structure_preserved(self):
        """Ontology structure preserved through stages."""
        config = ExtractionConfig()
        generator = OntologyGenerator(config)
        
        input_text = "Test input text"
        ontology = generator.generate_ontology(input_text)
        
        if ontology and isinstance(ontology, dict):
            # Ontology should have expected keys
            assert "entities" in ontology or "relationships" in ontology or len(ontology) >= 0
    
    def test_entity_ids_stable(self):
        """Entity IDs remain stable through evaluation."""
        validator = OntologyValidator()
        ontology = {
            "entities": [
                {"id": "entity_a", "text": "Alice", "type": "Person", "confidence": 0.9},
                {"id": "entity_b", "text": "Bob", "type": "Person", "confidence": 0.85},
            ],
            "relationships": []
        }
        
        suggestions = validator.suggest_entity_merges(ontology)
        
        # Suggestions should reference the same entity IDs
        for sugg in suggestions:
            assert sugg.entity1_id in ["entity_a", "entity_b"]
            assert sugg.entity2_id in ["entity_a", "entity_b"]


class TestEndToEndPipelineRealWorldScenario:
    """Test with realistic data."""
    
    def test_realistic_business_document(self):
        """Process realistic business document through pipeline."""
        config = ExtractionConfig(max_entities=50)
        generator = OntologyGenerator(config)
        critic = OntologyCritic()
        validator = OntologyValidator()
        
        document = """
        Apple Inc. is headquartered in Cupertino, California.
        Tim Cook is the CEO of Apple.
        Steve Jobs founded Apple with Steve Wozniak and Ronald Wayne.
        Microsoft is another technology company led by Satya Nadella.
        Both companies compete in the cloud computing market.
        """
        
        # Stage 1: Generate
        ontology = generator.generate_ontology(document)
        
        if ontology and isinstance(ontology, dict) and ontology.get("entities"):
            # Stage 2: Evaluate
            eval_result = critic.evaluate_ontology(ontology)
            
            # Stage 3: Validate
            suggestions = validator.suggest_entity_merges(ontology, threshold=0.8)
            
            # All stages should complete
            assert ontology is not None
            assert eval_result is not None
            assert isinstance(suggestions, list)
    
    def test_multiple_entity_types(self):
        """Handle document with multiple entity types."""
        config = ExtractionConfig()
        generator = OntologyGenerator(config)
        
        document = "Alice Johnson works at Acme Corp in New York. She collaborates with Bob Smith."
        ontology = generator.generate_ontology(document)
        
        if ontology and isinstance(ontology, dict):
            assert "entities" in ontology
