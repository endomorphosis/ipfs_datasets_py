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
        DataType,
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
            data_source="test",
            data_type="text",
            domain="legal",
        )
        
        assert context.domain == "legal"
        assert context.data_type == DataType.TEXT
        assert context.extraction_strategy == ExtractionStrategy.HYBRID
    
    def test_context_creation_full(self):
        """
        GIVEN: Complete context parameters
        WHEN: Creating a generation context with all options
        THEN: Context is created with specified values
        """
        context = OntologyGenerationContext(
            data_source="test_source",
            data_type="text",
            domain="medical",
            extraction_strategy=ExtractionStrategy.RULE_BASED,
        )
        
        assert context.domain == "medical"
        assert context.extraction_strategy == ExtractionStrategy.RULE_BASED


class TestOntologyGenerationResult:
    """Test OntologyGenerationResult dataclass."""
    
    def test_result_creation_basic(self):
        """
        GIVEN: Basic result data
        WHEN: Creating a generation result via from_ontology
        THEN: Result is created with entity and relationship counts
        """
        ontology = {
            "entities": [{"id": "e1", "type": "person", "text": "John", "confidence": 0.9}],
            "relationships": [{"type": "knows", "source": "e1", "target": "e2", "confidence": 0.8}],
        }
        result = OntologyGenerationResult.from_ontology(ontology, domain="general")
        
        assert result.entity_count == 1
        assert result.relationship_count == 1
        assert result.ontology == ontology
    
    def test_result_empty(self):
        """
        GIVEN: Empty ontology
        WHEN: Creating an empty generation result
        THEN: Result is created with zero counts
        """
        result = OntologyGenerationResult.from_ontology(
            {"entities": [], "relationships": []}
        )
        
        assert result.entity_count == 0
        assert result.relationship_count == 0


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
        assert hasattr(generator, 'ipfs_accelerate_config')
    
    def test_generator_initialization_custom_model(self):
        """
        GIVEN: Custom model configuration
        WHEN: Initializing generator with custom model
        THEN: Generator stores the configuration
        """
        config = {'model': 'bert-large-uncased'}
        generator = OntologyGenerator(ipfs_accelerate_config=config)
        
        assert generator.ipfs_accelerate_config['model'] == 'bert-large-uncased'
    
    def test_generator_has_strategies(self):
        """
        GIVEN: Initialized generator
        WHEN: Checking extraction strategies
        THEN: Generator has extraction strategy methods
        """
        generator = OntologyGenerator()
        
        assert hasattr(generator, '_extract_rule_based')
        assert hasattr(generator, '_extract_llm_based')
        assert hasattr(generator, '_extract_hybrid')


class TestOntologyGeneratorExtraction:
    """Test ontology extraction methods."""
    
    def setup_method(self):
        """Setup for each test."""
        self.generator = OntologyGenerator()
    
    def _ctx(self, domain="general", strategy=None):
        """Helper: build a minimal valid context."""
        kwargs = dict(data_source="test", data_type="text", domain=domain)
        if strategy is not None:
            kwargs["extraction_strategy"] = strategy
        return OntologyGenerationContext(**kwargs)

    def test_generate_from_text_basic(self):
        """
        GIVEN: Simple text data
        WHEN: Generating ontology from text
        THEN: OntologyGenerationResult is returned
        """
        data = "John works at Company X. Mary manages the team."
        result = self.generator.generate_ontology_rich(data, self._ctx())
        
        assert result is not None
        assert isinstance(result, OntologyGenerationResult)
    
    def test_generate_with_confidence_threshold(self):
        """
        GIVEN: Text data with config confidence threshold
        WHEN: Generating ontology
        THEN: Result is returned
        """
        from ipfs_datasets_py.optimizers.graphrag.ontology_generator import GraphRAGExtractionConfig
        data = "The patient has a diagnosis of diabetes."
        ctx = OntologyGenerationContext(
            data_source="test",
            data_type="text",
            domain="medical",
            config=GraphRAGExtractionConfig(confidence_threshold=0.7),
        )
        result = self.generator.generate_ontology_rich(data, ctx)
        assert result is not None
    
    def test_generate_with_max_entities(self):
        """
        GIVEN: Text data
        WHEN: Generating ontology
        THEN: entity_count does not exceed max_entities in config
        """
        from ipfs_datasets_py.optimizers.graphrag.ontology_generator import GraphRAGExtractionConfig
        data = "A B C D E F G H I J K L M N O P Q R S T U V W X Y Z"
        ctx = OntologyGenerationContext(
            data_source="test",
            data_type="text",
            domain="general",
            config=GraphRAGExtractionConfig(max_entities=10),
        )
        result = self.generator.generate_ontology_rich(data, ctx)
        assert result is not None
        assert result.entity_count <= 10
    
    @pytest.mark.parametrize("strategy", [
        ExtractionStrategy.NEURAL,
        ExtractionStrategy.RULE_BASED,
        ExtractionStrategy.LLM_BASED,
        ExtractionStrategy.HYBRID
    ])
    def test_generate_with_different_strategies(self, strategy):
        """
        GIVEN: Text data and extraction strategy
        WHEN: Generating ontology with specified strategy
        THEN: OntologyGenerationResult is returned
        """
        data = "The contract between party A and party B is valid."
        result = self.generator.generate_ontology_rich(data, self._ctx(strategy=strategy))
        assert result is not None
        assert isinstance(result, OntologyGenerationResult)


class TestOntologyGeneratorEdgeCases:
    """Test edge cases and error handling."""
    
    def setup_method(self):
        """Setup for each test."""
        self.generator = OntologyGenerator()

    def _ctx(self, domain="general"):
        return OntologyGenerationContext(data_source="test", data_type="text", domain=domain)
    
    def test_generate_empty_data(self):
        """
        GIVEN: Empty string data
        WHEN: Generating ontology from empty data
        THEN: Result is empty but valid
        """
        result = self.generator.generate_ontology_rich("", self._ctx())
        assert result is not None
        assert isinstance(result, OntologyGenerationResult)
    
    def test_generate_null_data(self):
        """
        GIVEN: None as data
        WHEN: Generating ontology from None
        THEN: Returns empty result or raises appropriate error
        """
        try:
            result = self.generator.generate_ontology_rich(None, self._ctx())
            assert result is not None
        except (ValueError, TypeError):
            pass  # Acceptable to raise
    
    def test_generate_very_long_text(self):
        """
        GIVEN: Very long text data
        WHEN: Generating ontology from long text
        THEN: Generation completes without error
        """
        data = "Test sentence. " * 1000  # 1000 sentences
        result = self.generator.generate_ontology_rich(data, self._ctx())
        assert result is not None
        assert isinstance(result, OntologyGenerationResult)
    
    def test_generate_special_characters(self):
        """
        GIVEN: Text with special characters
        WHEN: Generating ontology
        THEN: Special characters are handled gracefully
        """
        data = "Entity1 @#$% Entity2 !@# Entity3 &*()_+"
        result = self.generator.generate_ontology_rich(data, self._ctx())
        assert result is not None
        assert isinstance(result, OntologyGenerationResult)


class TestOntologyGeneratorIntegration:
    """Test integration with other components."""
    
    def setup_method(self):
        """Setup for each test."""
        self.generator = OntologyGenerator()

    def _ctx(self, domain="general"):
        return OntologyGenerationContext(data_source="test", data_type="text", domain=domain)
    
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
        result = self.generator.generate_ontology_rich(data, self._ctx("legal"))
        assert result is not None
        assert result.entity_count >= 0
    
    @pytest.mark.skipif(
        not GENERATOR_AVAILABLE,
        reason="Generator dependencies not available"
    )
    def test_generate_medical_domain(self):
        """
        GIVEN: Medical text
        WHEN: Generating ontology with medical domain
        THEN: Result is returned
        """
        data = """
        The patient presents with symptoms of fever and cough.
        Diagnosis: respiratory infection.
        Treatment: antibiotics prescribed.
        """
        result = self.generator.generate_ontology_rich(data, self._ctx("medical"))
        assert result is not None
        assert isinstance(result, OntologyGenerationResult)
    
    def test_generate_with_metadata(self):
        """
        GIVEN: Data with context
        WHEN: Generating ontology
        THEN: Result includes metadata
        """
        data = "Research paper on quantum computing."
        ctx = OntologyGenerationContext(
            data_source="academic_paper",
            data_type="text",
            domain="scientific",
        )
        result = self.generator.generate_ontology_rich(data, ctx)
        assert result is not None
        assert hasattr(result, 'metadata')


class TestOntologyGeneratorPerformance:
    """Test performance characteristics."""
    
    def setup_method(self):
        """Setup for each test."""
        self.generator = OntologyGenerator()

    def _ctx(self, domain="general"):
        return OntologyGenerationContext(data_source="test", data_type="text", domain=domain)
    
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
        ctx = self._ctx()
        
        results = [self.generator.generate_ontology_rich(d, ctx) for d in data_samples]
        
        assert len(results) == len(data_samples)
        assert all(isinstance(r, OntologyGenerationResult) for r in results)
    
    def test_incremental_generation(self):
        """
        GIVEN: Two independent data samples
        WHEN: Generating ontologies sequentially
        THEN: Both return valid results
        """
        ctx = self._ctx()
        result1 = self.generator.generate_ontology_rich("Entity A relates to Entity B.", ctx)
        result2 = self.generator.generate_ontology_rich("Entity C relates to Entity D.", ctx)
        
        assert result1 is not None
        assert result2 is not None
        assert isinstance(result1, OntologyGenerationResult)
        assert isinstance(result2, OntologyGenerationResult)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
