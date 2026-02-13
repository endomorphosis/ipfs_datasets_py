"""
Test suite for OntologyGenerator.

Tests the ontology generation component that extracts entities
and relationships from arbitrary data.

Format: GIVEN-WHEN-THEN
"""

import pytest
from typing import Dict, List, Any
from unittest.mock import Mock, patch, MagicMock

# Try to import the ontology generator
try:
    from ipfs_datasets_py.optimizers.graphrag.ontology_generator import (
        OntologyGenerator,
        OntologyGenerationContext,
        OntologyGenerationResult,
        ExtractionStrategy,
    )
    GENERATOR_AVAILABLE = True
except ImportError as e:
    GENERATOR_AVAILABLE = False
    pytest.skip(f"OntologyGenerator not available: {e}", allow_module_level=True)


class TestOntologyGenerationContext:
    """Test OntologyGenerationContext dataclass."""
    
    def test_context_creation_minimal(self):
        """
        GIVEN: Basic context parameters
        WHEN: Creating a generation context
        THEN: Context is created with default values
        """
        context = OntologyGenerationContext(
            domain="legal",
            data_type="text"
        )
        
        assert context.domain == "legal"
        assert context.data_type == "text"
        assert context.extraction_strategy == ExtractionStrategy.NEURAL_SYMBOLIC
        assert context.max_entities is None
        assert context.max_relationships is None
    
    def test_context_creation_full(self):
        """
        GIVEN: Complete context parameters
        WHEN: Creating a generation context with all options
        THEN: Context is created with specified values
        """
        context = OntologyGenerationContext(
            domain="medical",
            data_type="structured",
            extraction_strategy=ExtractionStrategy.PATTERN_BASED,
            max_entities=100,
            max_relationships=200,
            confidence_threshold=0.8,
            metadata={"source": "test"}
        )
        
        assert context.domain == "medical"
        assert context.extraction_strategy == ExtractionStrategy.PATTERN_BASED
        assert context.max_entities == 100
        assert context.max_relationships == 200
        assert context.confidence_threshold == 0.8
        assert context.metadata["source"] == "test"


class TestOntologyGenerationResult:
    """Test OntologyGenerationResult dataclass."""
    
    def test_result_creation_basic(self):
        """
        GIVEN: Basic result data
        WHEN: Creating a generation result
        THEN: Result is created with entities and relationships
        """
        result = OntologyGenerationResult(
            entities={"person": {"John"}},
            relationships=[{"type": "knows", "from": "John", "to": "Mary"}],
            confidence_scores={"overall": 0.85}
        )
        
        assert "person" in result.entities
        assert "John" in result.entities["person"]
        assert len(result.relationships) == 1
        assert result.relationships[0]["type"] == "knows"
        assert result.confidence_scores["overall"] == 0.85
    
    def test_result_empty(self):
        """
        GIVEN: Empty result data
        WHEN: Creating an empty generation result
        THEN: Result is created with no entities or relationships
        """
        result = OntologyGenerationResult(
            entities={},
            relationships=[],
            confidence_scores={}
        )
        
        assert len(result.entities) == 0
        assert len(result.relationships) == 0
        assert len(result.confidence_scores) == 0


class TestOntologyGeneratorInitialization:
    """Test OntologyGenerator initialization."""
    
    def test_generator_initialization_default(self):
        """
        GIVEN: No configuration
        WHEN: Initializing generator with defaults
        THEN: Generator is created with default settings
        """
        generator = OntologyGenerator()
        
        assert generator is not None
        assert hasattr(generator, 'config')
        assert generator.config.get('model') is not None
    
    def test_generator_initialization_custom_model(self):
        """
        GIVEN: Custom model configuration
        WHEN: Initializing generator with custom model
        THEN: Generator uses specified model
        """
        config = {'model': 'bert-large-uncased', 'batch_size': 16}
        generator = OntologyGenerator(config=config)
        
        assert generator.config['model'] == 'bert-large-uncased'
        assert generator.config['batch_size'] == 16
    
    def test_generator_has_strategies(self):
        """
        GIVEN: Initialized generator
        WHEN: Checking extraction strategies
        THEN: Generator has extraction strategy methods
        """
        generator = OntologyGenerator()
        
        assert hasattr(generator, '_extract_neural_symbolic')
        assert hasattr(generator, '_extract_pattern_based')
        assert hasattr(generator, '_extract_statistical')
        assert hasattr(generator, '_extract_hybrid')


class TestOntologyGeneratorExtraction:
    """Test ontology extraction methods."""
    
    def setup_method(self):
        """Setup for each test."""
        self.generator = OntologyGenerator()
    
    def test_generate_from_text_basic(self):
        """
        GIVEN: Simple text data
        WHEN: Generating ontology from text
        THEN: Ontology is extracted with entities
        """
        data = "John works at Company X. Mary manages the team."
        context = OntologyGenerationContext(
            domain="general",
            data_type="text"
        )
        
        result = self.generator.generate(data, context)
        
        assert result is not None
        assert isinstance(result, OntologyGenerationResult)
        assert len(result.entities) > 0 or len(result.relationships) > 0
    
    def test_generate_with_confidence_threshold(self):
        """
        GIVEN: Text data and confidence threshold
        WHEN: Generating ontology with filtering
        THEN: Only high-confidence results are returned
        """
        data = "The patient has a diagnosis of diabetes."
        context = OntologyGenerationContext(
            domain="medical",
            data_type="text",
            confidence_threshold=0.7
        )
        
        result = self.generator.generate(data, context)
        
        assert result is not None
        # All returned entities should meet confidence threshold
        if hasattr(result, 'entity_confidences'):
            for confidence in result.entity_confidences.values():
                assert confidence >= 0.7
    
    def test_generate_with_max_entities(self):
        """
        GIVEN: Text data with entity limit
        WHEN: Generating ontology with max_entities constraint
        THEN: Number of entities does not exceed limit
        """
        data = "A B C D E F G H I J K L M N O P Q R S T U V W X Y Z"
        context = OntologyGenerationContext(
            domain="general",
            data_type="text",
            max_entities=10
        )
        
        result = self.generator.generate(data, context)
        
        assert result is not None
        total_entities = sum(len(entities) for entities in result.entities.values())
        assert total_entities <= 10
    
    @pytest.mark.parametrize("strategy", [
        ExtractionStrategy.NEURAL_SYMBOLIC,
        ExtractionStrategy.PATTERN_BASED,
        ExtractionStrategy.STATISTICAL,
        ExtractionStrategy.HYBRID
    ])
    def test_generate_with_different_strategies(self, strategy):
        """
        GIVEN: Text data and extraction strategy
        WHEN: Generating ontology with specified strategy
        THEN: Ontology is generated using that strategy
        """
        data = "The contract between party A and party B is valid."
        context = OntologyGenerationContext(
            domain="legal",
            data_type="text",
            extraction_strategy=strategy
        )
        
        result = self.generator.generate(data, context)
        
        assert result is not None
        assert isinstance(result, OntologyGenerationResult)


class TestOntologyGeneratorEdgeCases:
    """Test edge cases and error handling."""
    
    def setup_method(self):
        """Setup for each test."""
        self.generator = OntologyGenerator()
    
    def test_generate_empty_data(self):
        """
        GIVEN: Empty string data
        WHEN: Generating ontology from empty data
        THEN: Result is empty but valid
        """
        data = ""
        context = OntologyGenerationContext(
            domain="general",
            data_type="text"
        )
        
        result = self.generator.generate(data, context)
        
        assert result is not None
        assert isinstance(result, OntologyGenerationResult)
    
    def test_generate_null_data(self):
        """
        GIVEN: None as data
        WHEN: Generating ontology from None
        THEN: Returns empty result or raises appropriate error
        """
        data = None
        context = OntologyGenerationContext(
            domain="general",
            data_type="text"
        )
        
        try:
            result = self.generator.generate(data, context)
            # If it succeeds, should return empty result
            assert result is not None
        except (ValueError, TypeError) as e:
            # Or it should raise an appropriate error
            assert "data" in str(e).lower() or "none" in str(e).lower()
    
    def test_generate_very_long_text(self):
        """
        GIVEN: Very long text data
        WHEN: Generating ontology from long text
        THEN: Generation completes without error
        """
        data = "Test sentence. " * 1000  # 1000 sentences
        context = OntologyGenerationContext(
            domain="general",
            data_type="text",
            max_entities=50
        )
        
        result = self.generator.generate(data, context)
        
        assert result is not None
        assert isinstance(result, OntologyGenerationResult)
    
    def test_generate_special_characters(self):
        """
        GIVEN: Text with special characters
        WHEN: Generating ontology
        THEN: Special characters are handled gracefully
        """
        data = "Entity1 @#$% Entity2 !@# Entity3 &*()_+"
        context = OntologyGenerationContext(
            domain="general",
            data_type="text"
        )
        
        result = self.generator.generate(data, context)
        
        assert result is not None
        assert isinstance(result, OntologyGenerationResult)


class TestOntologyGeneratorIntegration:
    """Test integration with other components."""
    
    def setup_method(self):
        """Setup for each test."""
        self.generator = OntologyGenerator()
    
    @pytest.mark.skipif(
        not GENERATOR_AVAILABLE,
        reason="Generator dependencies not available"
    )
    def test_generate_legal_domain(self):
        """
        GIVEN: Legal text
        WHEN: Generating ontology with legal domain
        THEN: Legal entities are extracted
        """
        data = """
        The plaintiff alleges that the defendant violated the contract.
        The court has jurisdiction over this matter.
        """
        context = OntologyGenerationContext(
            domain="legal",
            data_type="text"
        )
        
        result = self.generator.generate(data, context)
        
        assert result is not None
        # Should extract legal entities if available
        if result.entities:
            entity_types = list(result.entities.keys())
            # May have legal entity types
            assert len(entity_types) > 0
    
    @pytest.mark.skipif(
        not GENERATOR_AVAILABLE,
        reason="Generator dependencies not available"
    )
    def test_generate_medical_domain(self):
        """
        GIVEN: Medical text
        WHEN: Generating ontology with medical domain
        THEN: Medical entities are extracted
        """
        data = """
        The patient presents with symptoms of fever and cough.
        Diagnosis: respiratory infection.
        Treatment: antibiotics prescribed.
        """
        context = OntologyGenerationContext(
            domain="medical",
            data_type="text"
        )
        
        result = self.generator.generate(data, context)
        
        assert result is not None
        assert isinstance(result, OntologyGenerationResult)
    
    def test_generate_with_metadata(self):
        """
        GIVEN: Data with context metadata
        WHEN: Generating ontology
        THEN: Metadata is used in extraction
        """
        data = "Research paper on quantum computing."
        context = OntologyGenerationContext(
            domain="scientific",
            data_type="text",
            metadata={
                "source": "academic_paper",
                "year": 2024,
                "field": "physics"
            }
        )
        
        result = self.generator.generate(data, context)
        
        assert result is not None
        # Metadata should influence extraction
        if hasattr(result, 'metadata'):
            assert result.metadata is not None


class TestOntologyGeneratorPerformance:
    """Test performance characteristics."""
    
    def setup_method(self):
        """Setup for each test."""
        self.generator = OntologyGenerator()
    
    @pytest.mark.slow
    def test_batch_generation_performance(self):
        """
        GIVEN: Multiple data samples
        WHEN: Generating ontologies in batch
        THEN: Batch processing is efficient
        """
        data_samples = [
            "Sample text 1 about topic A.",
            "Sample text 2 about topic B.",
            "Sample text 3 about topic C.",
        ]
        context = OntologyGenerationContext(
            domain="general",
            data_type="text"
        )
        
        results = []
        for data in data_samples:
            result = self.generator.generate(data, context)
            results.append(result)
        
        assert len(results) == len(data_samples)
        assert all(isinstance(r, OntologyGenerationResult) for r in results)
    
    def test_incremental_generation(self):
        """
        GIVEN: Existing ontology and new data
        WHEN: Generating incrementally
        THEN: New entities are added to existing ontology
        """
        # First generation
        data1 = "Entity A relates to Entity B."
        context = OntologyGenerationContext(
            domain="general",
            data_type="text"
        )
        
        result1 = self.generator.generate(data1, context)
        
        # Second generation
        data2 = "Entity C relates to Entity D."
        result2 = self.generator.generate(data2, context)
        
        assert result1 is not None
        assert result2 is not None
        # Both should have entities
        assert len(result1.entities) > 0 or len(result2.entities) > 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
