"""
Comprehensive tests for language_router.py TypedDict contracts.

Tests validate:
1. LanguageMetadataDict structure and field types
2. MultilingualExtractionResultDict structure
3. to_standard_result() return type contracts
4. Language metdata consistency
5. Data flow through language-aware extraction
6. Type contract compliance
"""

import pytest
from typing import Dict, Any, List

from ipfs_datasets_py.optimizers.graphrag.language_router import (
    MultilingualExtractionResult,
    LanguageMetadataDict,
    MultilingualExtractionResultDict,
)


class TestLanguageMetadataDictType:
    """Validate LanguageMetadataDict structure and field types"""
    
    def test_language_metadata_dict_has_all_required_fields(self):
        """Verify LanguageMetadataDict contains all expected fields"""
        result = MultilingualExtractionResult(
            entities=[],
            relationships=[],
            detected_language="en",
            language_confidence=0.95,
            original_language_code="en",
            language_processing_notes=["test note"],
            confidence_adjustments_applied=True
        )
        
        metadata = result.to_standard_result()['language_metadata']
        
        assert 'detected_language' in metadata
        assert 'language_confidence' in metadata
        assert 'processing_notes' in metadata
        assert 'confidence_adjustments_applied' in metadata
    
    def test_detected_language_is_string(self):
        """Verify detected_language is string"""
        result = MultilingualExtractionResult(
            entities=[],
            relationships=[],
            detected_language="es",
            language_confidence=0.90,
            original_language_code="es",
            language_processing_notes=[],
            confidence_adjustments_applied=False
        )
        
        metadata = result.to_standard_result()['language_metadata']
        
        assert isinstance(metadata['detected_language'], str)
        assert metadata['detected_language'] == "es"
    
    def test_language_confidence_is_float_in_valid_range(self):
        """Verify language_confidence is float between 0 and 1"""
        result = MultilingualExtractionResult(
            entities=[],
            relationships=[],
            detected_language="fr",
            language_confidence=0.75,
            original_language_code="fr",
            language_processing_notes=[],
            confidence_adjustments_applied=False
        )
        
        metadata = result.to_standard_result()['language_metadata']
        
        assert isinstance(metadata['language_confidence'], float)
        assert 0.0 <= metadata['language_confidence'] <= 1.0
    
    def test_processing_notes_is_list_of_strings(self):
        """Verify processing_notes is list of strings"""
        notes = ["Note 1", "Note 2", "Confidence adjusted"]
        result = MultilingualExtractionResult(
            entities=[],
            relationships=[],
            detected_language="de",
            language_confidence=0.88,
            original_language_code="de",
            language_processing_notes=notes,
            confidence_adjustments_applied=True
        )
        
        metadata = result.to_standard_result()['language_metadata']
        
        assert isinstance(metadata['processing_notes'], list)
        assert all(isinstance(note, str) for note in metadata['processing_notes'])
        assert metadata['processing_notes'] == notes
    
    def test_confidence_adjustments_applied_is_boolean(self):
        """Verify confidence_adjustments_applied is boolean"""
        result = MultilingualExtractionResult(
            entities=[],
            relationships=[],
            detected_language="en",
            language_confidence=0.92,
            original_language_code="en",
            language_processing_notes=[],
            confidence_adjustments_applied=True
        )
        
        metadata = result.to_standard_result()['language_metadata']
        
        assert isinstance(metadata['confidence_adjustments_applied'], bool)
        assert metadata['confidence_adjustments_applied'] is True


class TestMultilingualExtractionResultDictType:
    """Validate MultilingualExtractionResultDict structure"""
    
    def test_result_dict_has_entities_relationships_and_metadata(self):
        """Verify result dict has all required top-level fields"""
        result = MultilingualExtractionResult(
            entities=[{"id": "e1", "text": "Entity", "type": "Test"}],
            relationships=[{"id": "r1", "source": "e1", "target": "e1"}],
            detected_language="pt",
            language_confidence=0.85,
            original_language_code="pt",
            language_processing_notes=[],
            confidence_adjustments_applied=False
        )
        
        result_dict = result.to_standard_result()
        
        assert 'entities' in result_dict
        assert 'relationships' in result_dict
        assert 'language_metadata' in result_dict
    
    def test_entities_field_is_list_of_dicts(self):
        """Verify entities field is list of dictionaries"""
        entities = [
            {"id": "e1", "text": "Entity 1", "type": "T1"},
            {"id": "e2", "text": "Entity 2", "type": "T2"}
        ]
        result = MultilingualExtractionResult(
            entities=entities,
            relationships=[],
            detected_language="en",
            language_confidence=0.9,
            original_language_code="en",
            language_processing_notes=[],
            confidence_adjustments_applied=False
        )
        
        result_dict = result.to_standard_result()
        
        assert isinstance(result_dict['entities'], list)
        assert len(result_dict['entities']) == 2
        assert all(isinstance(e, dict) for e in result_dict['entities'])
    
    def test_relationships_field_is_list_of_dicts(self):
        """Verify relationships field is list of dictionaries"""
        relationships = [
            {"id": "r1", "source": "e1", "target": "e2"},
            {"id": "r2", "source": "e2", "target": "e1"}
        ]
        result = MultilingualExtractionResult(
            entities=[],
            relationships=relationships,
            detected_language="en",
            language_confidence=0.9,
            original_language_code="en",
            language_processing_notes=[],
            confidence_adjustments_applied=False
        )
        
        result_dict = result.to_standard_result()
        
        assert isinstance(result_dict['relationships'], list)
        assert len(result_dict['relationships']) == 2
        assert all(isinstance(r, dict) for r in result_dict['relationships'])
    
    def test_language_metadata_is_dict(self):
        """Verify language_metadata is dictionary"""
        result = MultilingualExtractionResult(
            entities=[],
            relationships=[],
            detected_language="en",
            language_confidence=0.9,
            original_language_code="en",
            language_processing_notes=["test"],
            confidence_adjustments_applied=False
        )
        
        result_dict = result.to_standard_result()
        
        assert isinstance(result_dict['language_metadata'], dict)


class TestToStandardResultIntegration:
    """Integration tests for to_standard_result() method"""
    
    def test_to_standard_result_with_multiple_languages(self):
        """Test conversion with various language codes"""
        languages = ["en", "es", "fr", "de", "zh", "ja", "ar"]
        
        for lang in languages:
            result = MultilingualExtractionResult(
                entities=[{"id": "e1"}],
                relationships=[],
                detected_language=lang,
                language_confidence=0.9,
                original_language_code=lang,
                language_processing_notes=[],
                confidence_adjustments_applied=False
            )
            
            result_dict = result.to_standard_result()
            
            assert result_dict['language_metadata']['detected_language'] == lang
    
    def test_to_standard_result_preserves_entity_structure(self):
        """Verify entity structure is preserved through conversion"""
        entity = {
            "id": "entity_123",
            "text": "Test Entity",
            "type": "PERSON",
            "confidence": 0.95
        }
        result = MultilingualExtractionResult(
            entities=[entity],
            relationships=[],
            detected_language="en",
            language_confidence=0.9,
            original_language_code="en",
            language_processing_notes=[],
            confidence_adjustments_applied=False
        )
        
        result_dict = result.to_standard_result()
        converted_entity = result_dict['entities'][0]
        
        assert converted_entity['id'] == "entity_123"
        assert converted_entity['text'] == "Test Entity"
        assert converted_entity['type'] == "PERSON"
        assert converted_entity['confidence'] == 0.95
    
    def test_to_standard_result_preserves_relationship_structure(self):
        """Verify relationship structure is preserved through conversion"""
        relationship = {
            "id": "rel_456",
            "source": "e1",
            "target": "e2",
            "type": "KNOWS"
        }
        result = MultilingualExtractionResult(
            entities=[],
            relationships=[relationship],
            detected_language="en",
            language_confidence=0.9,
            original_language_code="en",
            language_processing_notes=[],
            confidence_adjustments_applied=False
        )
        
        result_dict = result.to_standard_result()
        converted_rel = result_dict['relationships'][0]
        
        assert converted_rel['id'] == "rel_456"
        assert converted_rel['source'] == "e1"
        assert converted_rel['target'] == "e2"
        assert converted_rel['type'] == "KNOWS"


class TestLanguageConfidenceValidation:
    """Validate language confidence values"""
    
    def test_language_confidence_boundary_values(self):
        """Test language confidence at boundary values"""
        test_values = [0.0, 0.25, 0.5, 0.75, 1.0]
        
        for conf in test_values:
            result = MultilingualExtractionResult(
                entities=[],
                relationships=[],
                detected_language="en",
                language_confidence=conf,
                original_language_code="en",
                language_processing_notes=[],
                confidence_adjustments_applied=False
            )
            
            result_dict = result.to_standard_result()
            
            assert result_dict['language_metadata']['language_confidence'] == conf
            assert 0.0 <= result_dict['language_metadata']['language_confidence'] <= 1.0


class TestProcessingNotes:
    """Validate processing notes handling"""
    
    def test_empty_processing_notes(self):
        """Verify empty processing notes list is handled"""
        result = MultilingualExtractionResult(
            entities=[],
            relationships=[],
            detected_language="en",
            language_confidence=0.9,
            original_language_code="en",
            language_processing_notes=[],
            confidence_adjustments_applied=False
        )
        
        result_dict = result.to_standard_result()
        
        assert isinstance(result_dict['language_metadata']['processing_notes'], list)
        assert len(result_dict['language_metadata']['processing_notes']) == 0
    
    def test_multiple_processing_notes(self):
        """Verify multiple processing notes are preserved"""
        notes = [
            "Language detected as English with 95% confidence",
            "Applied domain-specific vocabulary for medical terms",
            "Applied confidence adjustment for ambiguous entities"
        ]
        result = MultilingualExtractionResult(
            entities=[],
            relationships=[],
            detected_language="en",
            language_confidence=0.95,
            original_language_code="en",
            language_processing_notes=notes,
            confidence_adjustments_applied=True
        )
        
        result_dict = result.to_standard_result()
        
        assert result_dict['language_metadata']['processing_notes'] == notes
        assert len(result_dict['language_metadata']['processing_notes']) == 3


class TestTypeContractDataFlow:
    """Test data flow through type contracts"""
    
    def test_multilingual_extract_full_pipeline(self):
        """Test complete extraction pipeline with language metadata"""
        entities = [
            {"id": "e1", "text": "Paris", "type": "LOCATION"},
            {"id": "e2", "text": "France", "type": "COUNTRY"}
        ]
        relationships = [
            {"id": "r1", "source": "e1", "target": "e2", "type": "LOCATED-IN"}
        ]
        
        result = MultilingualExtractionResult(
            entities=entities,
            relationships=relationships,
            detected_language="fr",
            language_confidence=0.92,
            original_language_code="fr",
            language_processing_notes=[
                "Detected French text",
                "Applied French linguistic rules"
            ],
            confidence_adjustments_applied=True
        )
        
        result_dict = result.to_standard_result()
        
        # Verify structure
        assert len(result_dict['entities']) == 2
        assert len(result_dict['relationships']) == 1
        
        # Verify language metadata
        assert result_dict['language_metadata']['detected_language'] == "fr"
        assert result_dict['language_metadata']['language_confidence'] == 0.92
        assert len(result_dict['language_metadata']['processing_notes']) == 2
        assert result_dict['language_metadata']['confidence_adjustments_applied'] is True


class TestTypeContractConsistency:
    """Verify type contract consistency across calls"""
    
    def test_consistent_structure_across_multiple_calls(self):
        """Verify structure consistency when calling to_standard_result multiple times"""
        result = MultilingualExtractionResult(
            entities=[{"id": "e1"}],
            relationships=[],
            detected_language="en",
            language_confidence=0.9,
            original_language_code="en",
            language_processing_notes=[],
            confidence_adjustments_applied=False
        )
        
        result_dict_1 = result.to_standard_result()
        result_dict_2 = result.to_standard_result()
        
        # Both calls should return dicts with same keys
        assert set(result_dict_1.keys()) == set(result_dict_2.keys())
        assert result_dict_1 == result_dict_2


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
