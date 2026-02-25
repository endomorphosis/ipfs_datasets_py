"""
Comprehensive tests for integration_guide.py TypedDict contracts.

Tests validate:
1. ExtractionResultDict structure and field types
2. MultilingualProcessingResultDict structure
3. LanguageProcessingBatchDict structure
4. ConfigValidationResultDict structure
5. MergedConfigDict structure
6. CompletePipelineResultDict structure
7. Method return type contracts
"""

import pytest
from typing import Dict, Any, List
from unittest.mock import Mock, MagicMock, patch

from ipfs_datasets_py.optimizers.graphrag.integration_guide import (
    BasicOntologyExtraction,
    MultiLanguageWorkflow,
    ErrorHandlingPatterns,
    ConfigurationManagement,
    TransformationPipelines,
    AdvancedScenarios,
    ExtractionResultDict,
    MultilingualProcessingResultDict,
    LanguageProcessingBatchDict,
    ConfigValidationResultDict,
    MergedConfigDict,
    CompletePipelineResultDict,
)


class TestExtractionResultDictType:
    """Validate ExtractionResultDict structure and field types"""
    
    def test_basic_extraction_returns_extraction_result_dict(self):
        """Verify extract_and_validate returns ExtractionResultDict"""
        extractor = BasicOntologyExtraction()
        result = extractor.extract_and_validate("Sample text")
        
        assert isinstance(result, dict)
        assert 'entities' in result
        assert 'validation' in result
        assert isinstance(result['entities'], list)
    
    def test_extraction_result_dict_entities_field_is_list(self):
        """Verify entities field is list of dictionaries"""
        extractor = BasicOntologyExtraction()
        result = extractor.extract_and_validate("Test text")
        
        assert 'entities' in result
        assert isinstance(result['entities'], list)
        assert all(isinstance(e, dict) for e in result['entities'])
    
    def test_extraction_result_dict_validation_field_is_dict(self):
        """Verify validation field is dictionary"""
        extractor = BasicOntologyExtraction()
        result = extractor.extract_and_validate("Test")
        
        assert 'validation' in result
        assert isinstance(result['validation'], dict)
    
    def test_extraction_result_dict_has_optional_fields(self):
        """Verify optional fields can be present or absent"""
        extractor = BasicOntologyExtraction()
        result = extractor.extract_and_validate("Text")
        
        # Optional fields might be present or not
        optional_fields = ['fallback_language', 'minimal', 'errors', 'warnings']
        for field in optional_fields:
            # Field should either not exist or have correct type
            if field in result:
                if field == 'fallback_language':
                    assert isinstance(result[field], str)
                elif field == 'minimal':
                    assert isinstance(result[field], bool)
                elif field in ['errors', 'warnings']:
                    assert isinstance(result[field], list)
    
    def test_extraction_with_retry_returns_extraction_result_dict(self):
        """Verify extract_with_retry returns ExtractionResultDict"""
        extractor = BasicOntologyExtraction()
        result = extractor.extract_with_retry("Text", max_attempts=2)
        
        assert isinstance(result, dict)
        # Result could be empty dict or populated dict
        if result:
            assert isinstance(result, dict)


class TestMultilingualProcessingResultDictType:
    """Validate MultilingualProcessingResultDict structure"""
    
    def test_process_multilingual_text_returns_correct_structure(self):
        """Verify process_multilingual_text returns MultilingualProcessingResultDict"""
        with patch('ipfs_datasets_py.optimizers.graphrag.integration_guide.LanguageRouter'):
            workflow = MultiLanguageWorkflow()
            workflow.router.detect_language = Mock(return_value='es')
            workflow.router.get_language_config = Mock(
                return_value=Mock(
                    domain_vocab={'medical': ['term1', 'term2']},
                    language_name='Spanish'
                )
            )
            workflow.router.extract_with_language_awareness = Mock(
                return_value=Mock(
                    detected_language='es',
                    language_confidence=0.95,
                    entities=[],
                    relationships=[],
                    language_processing_notes='Processed as Spanish'
                )
            )
            
            result = workflow.process_multilingual_text("El texto", "medical")
            
            assert 'detected_language' in result
            assert 'language_confidence' in result
            assert 'entities' in result
            assert 'relationships' in result
            assert 'domain_vocab_size' in result
            assert 'processing_notes' in result
    
    def test_multilingual_result_detected_language_is_string(self):
        """Verify detected_language field is string"""
        with patch('ipfs_datasets_py.optimizers.graphrag.integration_guide.LanguageRouter'):
            workflow = MultiLanguageWorkflow()
            workflow.router.detect_language = Mock(return_value='fr')
            workflow.router.get_language_config = Mock(
                return_value=Mock(
                    domain_vocab={},
                    language_name='French'
                )
            )
            workflow.router.extract_with_language_awareness = Mock(
                return_value=Mock(
                    detected_language='fr',
                    language_confidence=0.92,
                    entities=[],
                    relationships=[],
                    language_processing_notes='French processing'
                )
            )
            
            result = workflow.process_multilingual_text("Texte", "general")
            
            assert isinstance(result['detected_language'], str)
            assert result['detected_language'] == 'fr'
    
    def test_multilingual_result_confidence_is_float(self):
        """Verify language_confidence field is float"""
        with patch('ipfs_datasets_py.optimizers.graphrag.integration_guide.LanguageRouter'):
            workflow = MultiLanguageWorkflow()
            workflow.router.detect_language = Mock(return_value='de')
            workflow.router.get_language_config = Mock(
                return_value=Mock(domain_vocab={}, language_name='German')
            )
            workflow.router.extract_with_language_awareness = Mock(
                return_value=Mock(
                    detected_language='de',
                    language_confidence=0.88,
                    entities=[],
                    relationships=[],
                    language_processing_notes='German'
                )
            )
            
            result = workflow.process_multilingual_text("Text", "general")
            
            assert isinstance(result['language_confidence'], float)
            assert 0.0 <= result['language_confidence'] <= 1.0


class TestLanguageProcessingBatchDictType:
    """Validate LanguageProcessingBatchDict structure"""
    
    def test_batch_process_languages_returns_list_of_dicts(self):
        """Verify batch_process_languages returns list of LanguageProcessingBatchDict"""
        with patch('ipfs_datasets_py.optimizers.graphrag.integration_guide.LanguageRouter'):
            workflow = MultiLanguageWorkflow()
            workflow.router.detect_language = Mock(side_effect=['en', 'es', 'fr'])
            workflow.router.get_language_config = Mock(
                return_value=Mock(language_name='Detected Language')
            )
            
            texts = [
                ("The person must comply", "en"),
                ("La persona debe cumplir", "es"),
                ("La personne doit se conformer", "fr"),
            ]
            results = workflow.batch_process_languages(texts)
            
            assert isinstance(results, list)
            assert len(results) == 3
            assert all(isinstance(r, dict) for r in results)
    
    def test_batch_result_has_language_fields(self):
        """Verify batch result items have language-related fields"""
        with patch('ipfs_datasets_py.optimizers.graphrag.integration_guide.LanguageRouter'):
            workflow = MultiLanguageWorkflow()
            workflow.router.detect_language = Mock(return_value='es')
            workflow.router.get_language_config = Mock(
                return_value=Mock(language_name='Spanish')
            )
            
            results = workflow.batch_process_languages([("Texto", "es")])
            
            assert len(results) > 0
            result = results[0]
            assert 'text' in result
            assert 'expected_language' in result
            assert 'detected_language' in result
            assert 'language_match' in result
            assert 'config_name' in result
    
    def test_batch_result_language_match_is_boolean(self):
        """Verify language_match field is boolean"""
        with patch('ipfs_datasets_py.optimizers.graphrag.integration_guide.LanguageRouter'):
            workflow = MultiLanguageWorkflow()
            workflow.router.detect_language = Mock(return_value='en')
            workflow.router.get_language_config = Mock(
                return_value=Mock(language_name='English')
            )
            
            results = workflow.batch_process_languages([("Text", "en")])
            
            result = results[0]
            assert isinstance(result['language_match'], bool)


class TestConfigValidationResultDictType:
    """Validate ConfigValidationResultDict structure"""
    
    def test_validate_extraction_config_returns_validation_result(self):
        """Verify validate_extraction_config returns ConfigValidationResultDict"""
        mgmt = ConfigurationManagement()
        config = {
            'confidence_threshold': 0.7,
            'max_entities': 100,
            'max_relationships': 200,
        }
        result = mgmt.validate_extraction_config(config)
        
        assert isinstance(result, dict)
        assert 'is_valid' in result
        assert 'errors' in result
        assert 'detected_issues' in result
    
    def test_validation_result_is_valid_is_boolean(self):
        """Verify is_valid field is boolean"""
        mgmt = ConfigurationManagement()
        result = mgmt.validate_extraction_config({})
        
        assert 'is_valid' in result
        assert isinstance(result['is_valid'], bool)
    
    def test_validation_result_errors_is_list(self):
        """Verify errors field is list of strings"""
        mgmt = ConfigurationManagement()
        result = mgmt.validate_extraction_config({'invalid_field': 'bad'})
        
        assert 'errors' in result
        assert isinstance(result['errors'], list)
        assert all(isinstance(e, str) for e in result['errors'])
    
    def test_validation_result_detected_issues_is_list_of_dicts(self):
        """Verify detected_issues field is list of dicts"""
        mgmt = ConfigurationManagement()
        result = mgmt.validate_extraction_config({})
        
        assert 'detected_issues' in result
        assert isinstance(result['detected_issues'], list)
        assert all(isinstance(issue, dict) for issue in result['detected_issues'])


class TestMergedConfigDictType:
    """Validate MergedConfigDict structure"""
    
    def test_merge_with_defaults_returns_merged_config_dict(self):
        """Verify merge_with_defaults returns MergedConfigDict"""
        mgmt = ConfigurationManagement()
        user_config = {'max_entities': 500}
        result = mgmt.merge_with_defaults(user_config)
        
        assert isinstance(result, dict)
        assert 'confidence_threshold' in result
        assert 'max_entities' in result
    
    def test_merged_config_has_numeric_thresholds(self):
        """Verify numeric fields are present and correct type"""
        mgmt = ConfigurationManagement()
        result = mgmt.merge_with_defaults({'max_entities': 750})
        
        assert 'confidence_threshold' in result
        assert isinstance(result['confidence_threshold'], (int, float))
        assert 'max_entities' in result
        assert isinstance(result['max_entities'], int)
    
    def test_merged_config_preserves_user_values(self):
        """Verify user-provided config values override defaults"""
        mgmt = ConfigurationManagement()
        user_max = 999
        result = mgmt.merge_with_defaults({'max_entities': user_max})
        
        assert result['max_entities'] == user_max
    
    def test_merged_config_with_custom_defaults(self):
        """Verify merge works with custom default config"""
        mgmt = ConfigurationManagement()
        custom_defaults = {'confidence_threshold': 0.9, 'max_entities': 50}
        result = mgmt.merge_with_defaults(
            {'max_relationships': 100},
            defaults=custom_defaults
        )
        
        assert result['confidence_threshold'] == 0.9
        assert result['max_entities'] == 50
        assert result['max_relationships'] == 100


class TestCompletePipelineResultDictType:
    """Validate CompletePipelineResultDict structure"""
    
    def test_complete_pipeline_returns_complete_result(self):
        """Verify complete_multilingual_pipeline returns CompletePipelineResultDict"""
        processor = AdvancedScenarios()
        config = {'confidence_threshold': 0.7}
        
        with patch('ipfs_datasets_py.optimizers.graphrag.integration_guide.LanguageRouter'):
            processor.language_router.detect_language = Mock(return_value='en')
            result = processor.complete_multilingual_pipeline("Text", config)
        
        assert isinstance(result, dict)
        assert 'steps_completed' in result
        assert 'errors' in result
        assert 'warnings' in result
    
    def test_pipeline_result_steps_completed_is_list(self):
        """Verify steps_completed is list of strings"""
        processor = AdvancedScenarios()
        
        with patch('ipfs_datasets_py.optimizers.graphrag.integration_guide.LanguageRouter'):
            processor.language_router.detect_language = Mock(return_value='en')
            result = processor.complete_multilingual_pipeline("Text", {})
        
        assert 'steps_completed' in result
        assert isinstance(result['steps_completed'], list)
        assert all(isinstance(step, str) for step in result['steps_completed'])
    
    def test_pipeline_result_errors_is_list_of_strings(self):
        """Verify errors field is list of strings"""
        processor = AdvancedScenarios()
        
        with patch('ipfs_datasets_py.optimizers.graphrag.integration_guide.LanguageRouter'):
            processor.language_router.detect_language = Mock(return_value='en')
            result = processor.complete_multilingual_pipeline("Text", {})
        
        assert 'errors' in result
        assert isinstance(result['errors'], list)
    
    def test_pipeline_result_detected_language_is_string(self):
        """Verify detected_language is string when present"""
        processor = AdvancedScenarios()
        
        with patch('ipfs_datasets_py.optimizers.graphrag.integration_guide.LanguageRouter'):
            processor.language_router.detect_language = Mock(return_value='fr')
            result = processor.complete_multilingual_pipeline("Texte", {})
        
        if 'detected_language' in result:
            assert isinstance(result['detected_language'], str)


class TestErrorHandlingPatterns:
    """Test error handling pathway return types"""
    
    def test_complex_extraction_with_recovery_returns_extraction_dict(self):
        """Verify complex_extraction_with_recovery returns ExtractionResultDict"""
        handler = ErrorHandlingPatterns()
        handler._primary_extraction = Mock(return_value={'entities': [], 'relationships': []})
        
        result = handler.complex_extraction_with_recovery("Text")
        
        assert isinstance(result, dict)
    
    def test_safe_extraction_returns_extraction_dict(self):
        """Verify safe_extraction returns ExtractionResultDict"""
        handler = ErrorHandlingPatterns()
        handler._primary_extraction = Mock(return_value={'entities': []})
        
        result = handler.safe_extraction("Text")
        
        assert isinstance(result, dict)
    
    def test_extraction_with_retry_returns_extraction_dict(self):
        """Verify extraction_with_retry returns ExtractionResultDict"""
        handler = ErrorHandlingPatterns()
        handler._primary_extraction = Mock(return_value={'entities': [], 'relationships': []})
        
        result = handler.extraction_with_retry("Text")
        
        assert isinstance(result, dict)


class TestTypeContractDataFlow:
    """Test data flow through type contracts"""
    
    def test_extraction_result_entity_preservation(self):
        """Verify entity data structure is preserved"""
        extractor = BasicOntologyExtraction()
        result = extractor.extract_and_validate("Sample")
        
        assert 'entities' in result
        entities = result['entities']
        
        # Each entity should be a dict with consistent structure
        for entity in entities:
            assert isinstance(entity, dict)
            assert 'id' in entity or 'text' in entity or 'type' in entity
    
    def test_multilingual_result_consistency(self):
        """Verify multilingual result has consistent field structure"""
        with patch('ipfs_datasets_py.optimizers.graphrag.integration_guide.LanguageRouter'):
            workflow = MultiLanguageWorkflow()
            workflow.router.detect_language = Mock(return_value='es')
            workflow.router.get_language_config = Mock(
                return_value=Mock(domain_vocab={}, language_name='Spanish')
            )
            workflow.router.extract_with_language_awareness = Mock(
                return_value=Mock(
                    detected_language='es',
                    language_confidence=0.90,
                    entities=[],
                    relationships=[],
                    language_processing_notes=''
                )
            )
            
            result = workflow.process_multilingual_text("Texto", "legal")
            
            # Verify all expected fields present
            expected_fields = ['detected_language', 'language_confidence', 'entities',
                             'relationships', 'domain_vocab_size', 'processing_notes']
            for field in expected_fields:
                assert field in result, f"Missing field: {field}"


class TestTypeContractConsistency:
    """Verify type contract consistency across methods"""
    
    def test_extraction_result_dict_multiple_calls_consistent(self):
        """Verify ExtractionResultDict structure is consistent"""
        extractor = BasicOntologyExtraction()
        
        result1 = extractor.extract_and_validate("Text1")
        result2 = extractor.extract_and_validate("Text2")
        
        # Both should have same top-level keys (allowing for optional fields)
        result1_keys = set(result1.keys())
        result2_keys = set(result2.keys())
        
        # At least entities and validation should be present
        assert 'entities' in result1_keys
        assert 'entities' in result2_keys
    
    def test_config_validation_result_dict_consistency(self):
        """Verify ConfigValidationResultDict is consistent across calls"""
        mgmt = ConfigurationManagement()
        
        result1 = mgmt.validate_extraction_config({'max_entities': 100})
        result2 = mgmt.validate_extraction_config({'max_entities': 200})
        
        # Both should have common fields
        assert 'is_valid' in result1 and 'is_valid' in result2
        assert 'errors' in result1 and 'errors' in result2
        assert 'detected_issues' in result1 and 'detected_issues' in result2


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
