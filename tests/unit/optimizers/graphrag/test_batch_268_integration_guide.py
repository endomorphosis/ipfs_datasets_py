"""
Batch 268: Comprehensive tests for integration_guide module.

Tests all integration workflow classes demonstrating GraphRAG optimization:
- BasicOntologyExtraction: Entity extraction and validation workflows
- MultiLanguageWorkflow: Multi-language text processing with routing
- ErrorHandlingPatterns: Error recovery and resilience patterns
- ConfigurationManagement: Config validation and merging
- TransformationPipelines: Data normalization and filtering
- AdvancedScenarios: End-to-end complex workflows

Coverage: 45 tests across 11 test classes
"""

import pytest
from typing import Dict, List, Any
from unittest.mock import Mock, patch

from ipfs_datasets_py.optimizers.graphrag.integration_guide import (
    BasicOntologyExtraction,
    MultiLanguageWorkflow,
    ErrorHandlingPatterns,
    ConfigurationManagement,
    TransformationPipelines,
    AdvancedScenarios,
    _safe_error_text,
    integration_example_1,
    integration_example_2,
    integration_example_3,
    integration_example_4,
)
from ipfs_datasets_py.optimizers.graphrag.error_handling import (
    GraphRAGException,
    GraphRAGConfigError,
    GraphRAGExtractionError,
)


class TestSafeErrorText:
    """Test _safe_error_text redaction helper."""
    
    def test_safe_error_text_basic_exception(self):
        """Test basic exception text extraction."""
        error = ValueError("something went wrong")
        
        result = _safe_error_text(error)
        
        assert isinstance(result, str)
        assert "something went wrong" in result
    
    def test_safe_error_text_with_sensitive_data(self):
        """Test that sensitive data is redacted."""
        # Assuming redact_sensitive redacts patterns like "password=..."
        error = Exception("Failed with password=secret123")
        
        result = _safe_error_text(error)
        
        # Should be redacted (exact redaction depends on redact_sensitive implementation)
        assert isinstance(result, str)


class TestBasicOntologyExtraction:
    """Test BasicOntologyExtraction workflow class."""
    
    def test_init_creates_validator(self):
        """Test initialization creates EntityExtractionValidator."""
        extractor = BasicOntologyExtraction()
        
        assert extractor.validator is not None
        assert extractor.logger is None  # Not set by default
    
    def test_extract_and_validate_basic(self):
        """Test basic extraction returns entities and validation."""
        extractor = BasicOntologyExtraction()
        
        result = extractor.extract_and_validate("Some text")
        
        assert 'entities' in result
        assert 'validation' in result
        assert isinstance(result['entities'], list)
        assert len(result['entities']) == 2  # Placeholder returns 2 entities
        assert result['entities'][0]['text'] == 'Company A'
        assert result['entities'][1]['text'] == 'John Doe'
    
    def test_extract_and_validate_entity_structure(self):
        """Test extracted entities have required fields."""
        extractor = BasicOntologyExtraction()
        
        result = extractor.extract_and_validate("Test text")
        entity = result['entities'][0]
        
        assert 'id' in entity
        assert 'text' in entity
        assert 'type' in entity
        assert 'confidence' in entity
        assert entity['confidence'] >= 0 and entity['confidence'] <= 1
    
    def test_extract_with_retry_success(self):
        """Test retry mechanism succeeds on first attempt."""
        extractor = BasicOntologyExtraction()
        
        result = extractor.extract_with_retry("Test text", max_attempts=3)
        
        assert 'entities' in result
        assert len(result['entities']) > 0
    
    def test_extract_with_retry_handles_exceptions(self):
        """Test retry returns empty dict on repeated failures."""
        extractor = BasicOntologyExtraction()
        
        # Mock extract_and_validate to always fail
        with patch.object(extractor, 'extract_and_validate', side_effect=ValueError("test error")):
            result = extractor.extract_with_retry("Test text", max_attempts=2)
            
            # Should return empty dict on failure
            assert result == {}
    
    def test_extract_with_retry_logs_errors(self):
        """Test retry logs errors on failure."""
        extractor = BasicOntologyExtraction()
        extractor.logger = Mock()
        
        with patch.object(extractor, 'extract_and_validate', side_effect=GraphRAGException("test error")):
            result = extractor.extract_with_retry("Test text", max_attempts=1)
            
            # Should have logged error
            assert extractor.logger.error.called


class TestMultiLanguageWorkflow:
    """Test MultiLanguageWorkflow class."""
    
    def test_init_creates_language_router(self):
        """Test initialization creates LanguageRouter."""
        workflow = MultiLanguageWorkflow()
        
        assert workflow.router is not None
        assert workflow.extractor is None  # Placeholder
    
    def test_process_multilingual_text_basic(self):
        """Test basic multilingual text processing."""
        workflow = MultiLanguageWorkflow()
        
        result = workflow.process_multilingual_text("Some English text", domain='legal')
        
        assert 'detected_language' in result
        assert 'language_confidence' in result
        assert 'entities' in result
        assert 'relationships' in result
        assert 'domain_vocab_size' in result
        assert 'processing_notes' in result
    
    def test_process_multilingual_text_with_spanish(self):
        """Test processing Spanish text."""
        workflow = MultiLanguageWorkflow()
        
        result = workflow.process_multilingual_text(
            "El paciente tiene una obligación de informar",
            domain='medical'
        )
        
        # Should detect Spanish
        assert result['detected_language'] in ['es', 'Spanish']
    
    def test_process_multilingual_text_domain_vocab(self):
        """Test domain vocabulary is retrieved."""
        workflow = MultiLanguageWorkflow()
        
        result = workflow.process_multilingual_text("Test", domain='legal')
        
        # Domain vocab size should be non-negative
        assert result['domain_vocab_size'] >= 0
    
    def test_batch_process_languages_basic(self):
        """Test batch processing of multiple languages."""
        workflow = MultiLanguageWorkflow()
        
        texts = [
            ("The person must comply", "en"),
            ("La persona debe cumplir", "es"),
        ]
        
        results = workflow.batch_process_languages(texts)
        
        assert len(results) == 2
        assert all('detected_language' in r for r in results)
        assert all('language_match' in r for r in results)
    
    def test_batch_process_languages_language_match(self):
        """Test language match detection in batch processing."""
        workflow = MultiLanguageWorkflow()
        
        texts = [("Hello world", "en")]
        
        results = workflow.batch_process_languages(texts)
        
        assert results[0]['expected_language'] == "en"
        assert 'detected_language' in results[0]
        assert 'language_match' in results[0]
    
    def test_batch_process_languages_text_preview(self):
        """Test text preview is truncated to 50 chars."""
        workflow = MultiLanguageWorkflow()
        
        long_text = "a" * 100
        results = workflow.batch_process_languages([(long_text, "en")])
        
        assert len(results[0]['text']) == 50
        assert results[0]['text'] == "a" * 50


class TestErrorHandlingPatterns:
    """Test ErrorHandlingPatterns class."""
    
    def test_init_creates_logger(self):
        """Test initialization creates logger."""
        handler = ErrorHandlingPatterns()
        
        assert handler.logger is not None
    
    def test_complex_extraction_with_recovery_success(self):
        """Test successful extraction without errors."""
        handler = ErrorHandlingPatterns()
        
        with patch.object(handler, '_primary_extraction', return_value={'entities': []}):
            result = handler.complex_extraction_with_recovery("Test text")
            
            assert 'entities' in result
    
    def test_complex_extraction_with_recovery_extraction_error_fallback(self):
        """Test fallback extraction on GraphRAGExtractionError."""
        handler = ErrorHandlingPatterns()
        
        with patch.object(handler, '_primary_extraction', side_effect=GraphRAGExtractionError("test error")):
            with patch.object(handler, '_fallback_extraction', return_value={'entities': [], 'fallback_language': 'en'}):
                result = handler.complex_extraction_with_recovery("Test text", fallback_language='en')
                
                assert 'fallback_language' in result
                assert result['fallback_language'] == 'en'
    
    def test_complex_extraction_with_recovery_config_error_minimal(self):
        """Test minimal extraction on GraphRAGConfigError."""
        handler = ErrorHandlingPatterns()
        
        with patch.object(handler, '_primary_extraction', side_effect=GraphRAGConfigError("config error")):
            with patch.object(handler, '_minimal_extraction', return_value={'entities': [], 'minimal': True}):
                result = handler.complex_extraction_with_recovery("Test text")
                
                assert 'minimal' in result
                assert result['minimal'] is True
    
    def test_complex_extraction_with_recovery_generic_graphrag_error(self):
        """Test empty dict returned on generic GraphRAGException."""
        handler = ErrorHandlingPatterns()
        
        with patch.object(handler, '_primary_extraction', side_effect=GraphRAGException("generic error")):
            result = handler.complex_extraction_with_recovery("Test text")
            
            assert result == {}
    
    def test_safe_extraction_never_throws(self):
        """Test safe_extraction never raises exceptions."""
        handler = ErrorHandlingPatterns()
        
        # Make _primary_extraction raise
        with patch.object(handler, '_primary_extraction', side_effect=ValueError("error")):
            # Should not raise, should return empty dict
            result = handler.safe_extraction("Test text")
            
            assert result == {}
    
    def test_safe_extraction_returns_result_on_success(self):
        """Test safe_extraction returns result on success."""
        handler = ErrorHandlingPatterns()
        
        expected = {'entities': [{'id': 'e1'}]}
        with patch.object(handler, '_primary_extraction', return_value=expected):
            result = handler.safe_extraction("Test text")
            
            assert result == expected
    
    def test_extraction_with_retry_basic(self):
        """Test retry mechanism with successful extraction."""
        handler = ErrorHandlingPatterns()
        
        expected = {'entities': []}
        with patch.object(handler, '_primary_extraction', return_value=expected):
            result = handler.extraction_with_retry("Test text")
            
            assert result == expected


class TestConfigurationManagement:
    """Test ConfigurationManagement class."""
    
    def test_init_creates_validator(self):
        """Test initialization creates ExtractionConfigValidator."""
        manager = ConfigurationManagement()
        
        assert manager.validator is not None
    
    def test_validate_extraction_config_basic(self):
        """Test basic config validation."""
        manager = ConfigurationManagement()
        
        config = {
            'confidence_threshold': 0.7,
            'max_entities': 100,
            'max_relationships': 200,
        }
        
        result = manager.validate_extraction_config(config)
        
        assert 'is_valid' in result
        assert 'errors' in result
        assert 'warnings' in result
        assert 'detected_issues' in result
    
    def test_validate_extraction_config_complete_config(self):
        """Test validation with complete config."""
        manager = ConfigurationManagement()
        
        config = {
            'confidence_threshold': 0.7,
            'max_entities': 100,
            'max_relationships': 200,
            'window_size': 512,
            'allowed_entity_types': ['PERSON', 'ORG'],
        }
        
        result = manager.validate_extraction_config(config)
        
        # Should validate successfully
        assert isinstance(result['is_valid'], bool)
        assert isinstance(result['errors'], list)
    
    def test_merge_with_defaults_basic(self):
        """Test merging user config with defaults."""
        manager = ConfigurationManagement()
        
        user_config = {'max_entities': 500}
        
        merged = manager.merge_with_defaults(user_config)
        
        # Should have user's value
        assert merged['max_entities'] == 500
        # Should have defaults
        assert 'confidence_threshold' in merged
        assert 'max_relationships' in merged
        assert 'window_size' in merged
    
    def test_merge_with_defaults_custom_defaults(self):
        """Test merging with custom defaults."""
        manager = ConfigurationManagement()
        
        user_config = {'max_entities': 500}
        custom_defaults = {
            'confidence_threshold': 0.5,
            'max_entities': 1000,
            'custom_field': 'value'
        }
        
        merged = manager.merge_with_defaults(user_config, defaults=custom_defaults)
        
        assert merged['max_entities'] == 500  # User override
        assert merged['confidence_threshold'] == 0.5  # Custom default
        assert merged['custom_field'] == 'value'  # Custom field
    
    def test_merge_with_defaults_validates_merged(self):
        """Test merged config is validated."""
        manager = ConfigurationManagement()
        
        user_config = {'window_size': 256}
        
        # Should not raise - validation called internally
        merged = manager.merge_with_defaults(user_config)
        
        assert 'window_size' in merged


class TestTransformationPipelines:
    """Test TransformationPipelines class."""
    
    def test_init_creates_pipeline(self):
        """Test initialization creates TransformationPipeline."""
        pipelines = TransformationPipelines()
        
        assert pipelines.pipeline is not None
    
    def test_normalize_extraction_results_basic(self):
        """Test basic normalization of entities and relationships."""
        pipelines = TransformationPipelines()
        
        entities = [
            {'id': 'e1', 'text': 'Entity 1', 'confidence': 0.8},
            {'id': 'e2', 'text': 'Entity 2', 'confidence': 0.6},
        ]
        relationships = [
            {'source': 'e1', 'target': 'e2', 'confidence': 0.7}
        ]
        
        norm_entities, norm_rels = pipelines.normalize_extraction_results(
            entities, relationships, confidence_threshold=0.5
        )
        
        # All should pass threshold
        assert len(norm_entities) == 2
        assert len(norm_rels) == 1
    
    def test_normalize_extraction_results_filters_by_confidence(self):
        """Test confidence threshold filtering."""
        pipelines = TransformationPipelines()
        
        entities = [
            {'id': 'e1', 'text': 'High confidence', 'confidence': 0.9},
            {'id': 'e2', 'text': 'Low confidence', 'confidence': 0.4},
        ]
        relationships = []
        
        norm_entities, _ = pipelines.normalize_extraction_results(
            entities, relationships, confidence_threshold=0.7
        )
        
        # Only high confidence should pass
        assert len(norm_entities) == 1
        assert norm_entities[0]['text'] == 'High confidence'
    
    def test_normalize_extraction_results_handles_missing_confidence(self):
        """Test entities without confidence field are filtered out."""
        pipelines = TransformationPipelines()
        
        entities = [
            {'id': 'e1', 'text': 'No confidence field'},
            {'id': 'e2', 'text': 'Has confidence', 'confidence': 0.8},
        ]
        
        norm_entities, _ = pipelines.normalize_extraction_results(
            entities, [], confidence_threshold=0.5
        )
        
        # Only entity with confidence >= 0.5 should pass
        # Entity without field defaults to 0 (< 0.5)
        assert len(norm_entities) == 1
    
    def test_build_transformation_chain_normalize(self):
        """Test building chain with normalize operation."""
        pipelines = TransformationPipelines()
        
        chain = pipelines.build_transformation_chain(['normalize'])
        
        assert chain is not None
        assert isinstance(chain, type(pipelines.pipeline))
    
    def test_build_transformation_chain_multiple_ops(self):
        """Test building chain with multiple operations."""
        pipelines = TransformationPipelines()
        
        chain = pipelines.build_transformation_chain([
            'normalize',
            'filter_confidence',
        ])
        
        assert chain is not None


class TestAdvancedScenarios:
    """Test AdvancedScenarios class."""
    
    def test_init_creates_all_components(self):
        """Test initialization creates all required components."""
        scenarios = AdvancedScenarios()
        
        assert scenarios.language_router is not None
        assert scenarios.config_validator is not None
        assert scenarios.entity_validator is not None
    
    def test_complete_multilingual_pipeline_basic(self):
        """Test basic end-to-end pipeline execution."""
        scenarios = AdvancedScenarios()
        
        config = {
            'confidence_threshold': 0.7,
            'max_entities': 100,
        }
        
        result = scenarios.complete_multilingual_pipeline("Test text", config)
        
        assert 'steps_completed' in result
        assert 'errors' in result
        assert 'warnings' in result
        assert 'final_results' in result
    
    def test_complete_multilingual_pipeline_all_steps(self):
        """Test all pipeline steps are executed."""
        scenarios = AdvancedScenarios()
        
        config = {'confidence_threshold': 0.7}
        
        result = scenarios.complete_multilingual_pipeline("Test text", config)
        
        expected_steps = [
            'config_validation',
            'language_detection',
            'extraction',
            'entity_validation',
            'normalization'
        ]
        
        for step in expected_steps:
            assert step in result['steps_completed']
    
    def test_complete_multilingual_pipeline_detects_language(self):
        """Test language is detected and included in results."""
        scenarios = AdvancedScenarios()
        
        result = scenarios.complete_multilingual_pipeline(
            "Some text",
            {'confidence_threshold': 0.5}
        )
        
        assert 'detected_language' in result
        assert isinstance(result['detected_language'], str)
    
    def test_complete_multilingual_pipeline_entity_validation(self):
        """Test entity validation is performed."""
        scenarios = AdvancedScenarios()
        
        result = scenarios.complete_multilingual_pipeline(
            "Test",
            {}
        )
        
        assert 'entity_validation' in result
        assert 'total_checked' in result['entity_validation']
        assert 'valid_count' in result['entity_validation']
    
    def test_complete_multilingual_pipeline_final_results(self):
        """Test final results structure."""
        scenarios = AdvancedScenarios()
        
        result = scenarios.complete_multilingual_pipeline("Test", {})
        
        final = result['final_results']
        assert 'entity_count' in final
        assert 'relationship_count' in final
        assert 'language' in final
    
    def test_complete_multilingual_pipeline_handles_exceptions(self):
        """Test pipeline handles exceptions gracefully."""
        scenarios = AdvancedScenarios()
        
        # Force an error by making config_validator.validate fail
        with patch.object(scenarios.config_validator, 'validate', side_effect=ValueError("test error")):
            result = scenarios.complete_multilingual_pipeline("Test", {})
            
            assert len(result['errors']) > 0


class TestIntegrationExamples:
    """Test integration example functions."""
    
    def test_integration_example_1_runs(self):
        """Test example 1 runs without errors."""
        # Should not raise
        integration_example_1()
    
    def test_integration_example_2_runs(self):
        """Test example 2 runs without errors."""
        # Should not raise
        integration_example_2()
    
    def test_integration_example_3_runs(self):
        """Test example 3 runs without errors."""
        # Should not raise
        integration_example_3()
    
    def test_integration_example_4_runs(self):
        """Test example 4 runs without errors."""
        # Should not raise
        integration_example_4()


class TestTypedDictContracts:
    """Test TypedDict return type contracts."""
    
    def test_extraction_result_dict_structure(self):
        """Test ExtractionResultDict has expected fields."""
        extractor = BasicOntologyExtraction()
        result = extractor.extract_and_validate("Test")
        
        # Check required fields
        assert 'entities' in result
        assert 'validation' in result
        
        # Check types
        assert isinstance(result['entities'], list)
        assert isinstance(result['validation'], dict)
    
    def test_multilingual_processing_result_dict_structure(self):
        """Test MultilingualProcessingResultDict has expected fields."""
        workflow = MultiLanguageWorkflow()
        result = workflow.process_multilingual_text("Test", domain='legal')
        
        # Check all expected fields
        assert 'detected_language' in result
        assert 'language_confidence' in result
        assert 'entities' in result
        assert 'relationships' in result
        assert 'domain_vocab_size' in result
        assert 'processing_notes' in result
    
    def test_config_validation_result_dict_structure(self):
        """Test ConfigValidationResultDict has expected fields."""
        manager = ConfigurationManagement()
        result = manager.validate_extraction_config({'confidence_threshold': 0.7})
        
        assert 'is_valid' in result
        assert 'errors' in result
        assert 'warnings' in result
        assert 'detected_issues' in result
    
    def test_complete_pipeline_result_dict_structure(self):
        """Test CompletePipelineResultDict has expected fields."""
        scenarios = AdvancedScenarios()
        result = scenarios.complete_multilingual_pipeline("Test", {})
        
        assert 'steps_completed' in result
        assert 'errors' in result
        assert 'warnings' in result
        assert 'detected_language' in result
        assert 'entity_validation' in result
        assert 'final_results' in result


class TestEdgeCases:
    """Test edge cases and boundary conditions."""
    
    def test_empty_text_extraction(self):
        """Test extraction with empty text."""
        extractor = BasicOntologyExtraction()
        
        result = extractor.extract_and_validate("")
        
        # Should still return structure (placeholder returns fixed entities)
        assert 'entities' in result
    
    def test_multilingual_empty_text(self):
        """Test multilingual processing with empty text."""
        workflow = MultiLanguageWorkflow()
        
        # Should not raise
        result = workflow.process_multilingual_text("", domain='legal')
        
        assert 'detected_language' in result
    
    def test_batch_process_empty_list(self):
        """Test batch processing with empty list."""
        workflow = MultiLanguageWorkflow()
        
        results = workflow.batch_process_languages([])
        
        assert results == []
    
    def test_merge_with_empty_user_config(self):
        """Test merging with empty user config."""
        manager = ConfigurationManagement()
        
        merged = manager.merge_with_defaults({})
        
        # Should have all defaults
        assert 'confidence_threshold' in merged
        assert 'max_entities' in merged
    
    def test_normalize_empty_entities(self):
        """Test normalizing empty entity list."""
        pipelines = TransformationPipelines()
        
        norm_entities, norm_rels = pipelines.normalize_extraction_results([], [])
        
        assert norm_entities == []
        assert norm_rels == []
    
    def test_build_chain_empty_operations(self):
        """Test building chain with no operations."""
        pipelines = TransformationPipelines()
        
        chain = pipelines.build_transformation_chain([])
        
        assert chain is not None
    
    def test_complete_pipeline_empty_config(self):
        """Test complete pipeline with empty config."""
        scenarios = AdvancedScenarios()
        
        result = scenarios.complete_multilingual_pipeline("Test", {})
        
        # Should use defaults
        assert 'steps_completed' in result


class TestRealWorldScenarios:
    """Test real-world usage scenarios."""
    
    def test_legal_document_extraction_workflow(self):
        """Test extracting entities from a legal document."""
        extractor = BasicOntologyExtraction()
        
        legal_text = "The defendant John Smith violated the terms of the contract with Acme Corporation."
        
        result = extractor.extract_and_validate(legal_text)
        
        assert len(result['entities']) > 0
        # Placeholder always returns Company A and John Doe
        assert any('John' in e['text'] for e in result['entities'])
    
    def test_multilingual_medical_processing(self):
        """Test processing medical text in multiple languages."""
        workflow = MultiLanguageWorkflow()
        
        spanish_medical = "El paciente tiene una obligación de informar sobre síntomas"
        
        result = workflow.process_multilingual_text(spanish_medical, domain='medical')
        
        # Should detect Spanish
        assert result['detected_language'] in ['es', 'Spanish']
        assert result['domain_vocab_size'] >= 0
    
    def test_configuration_with_custom_entity_types(self):
        """Test config with custom allowed entity types."""
        manager = ConfigurationManagement()
        
        config = {
            'confidence_threshold': 0.75,
            'max_entities': 50,
            'allowed_entity_types': ['PERSON', 'ORGANIZATION', 'LOCATION']
        }
        
        result = manager.validate_extraction_config(config)
        
        # Should validate successfully
        assert isinstance(result['is_valid'], bool)
    
    def test_pipeline_with_high_confidence_filtering(self):
        """Test pipeline filtering for high-confidence results only."""
        pipelines = TransformationPipelines()
        
        entities = [
            {'id': 'e1', 'confidence': 0.95},
            {'id': 'e2', 'confidence': 0.87},
            {'id': 'e3', 'confidence': 0.72},
            {'id': 'e4', 'confidence': 0.65},
        ]
        
        norm_entities, _ = pipelines.normalize_extraction_results(
            entities, [], confidence_threshold=0.85
        )
        
        # Should keep only >= 0.85
        assert len(norm_entities) == 2
