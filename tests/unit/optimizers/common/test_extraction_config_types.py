"""
Tests for ExtractionConfig type utilities and validation.
"""

import pytest
from ipfs_datasets_py.optimizers.common.extraction_config_types import (
    get_extraction_config_type_hints,
    validate_extraction_config_field,
    create_extraction_config_from_typed_dict,
    get_extraction_config_field_info,
)
from ipfs_datasets_py.optimizers.graphrag.ontology_generator import ExtractionConfig


class TestExtractionConfigTypeHints:
    """Tests for type hint retrieval."""

    def test_get_type_hints_returns_dict(self):
        """Verify type hints are returned as dictionary."""
        hints = get_extraction_config_type_hints()
        assert isinstance(hints, dict)

    def test_all_fields_have_type_hints(self):
        """Verify all ExtractionConfig fields have type hints."""
        hints = get_extraction_config_type_hints()
        
        expected_fields = {
            'confidence_threshold', 'max_entities', 'max_relationships',
            'window_size', 'min_entity_length', 'stopwords',
            'allowed_entity_types', 'domain_vocab', 'custom_rules',
            'llm_fallback_threshold', 'max_confidence', 'include_properties'
        }
        
        for field in expected_fields:
            assert field in hints, f"Missing type hint for {field}"

    def test_type_hint_accuracy(self):
        """Verify type hints match field types."""
        hints = get_extraction_config_type_hints()
        
        assert hints['confidence_threshold'] == float
        assert hints['max_entities'] == int
        assert hints['window_size'] == int
        assert hints['include_properties'] == bool


class TestFieldValidation:
    """Tests for field value validation."""

    def test_validate_valid_confidence_threshold(self):
        """Verify valid confidence threshold passes validation."""
        assert validate_extraction_config_field('confidence_threshold', 0.75)

    def test_validate_valid_max_entities(self):
        """Verify valid max_entities passes validation."""
        assert validate_extraction_config_field('max_entities', 1000)
        assert validate_extraction_config_field('max_entities', 0)

    def test_validate_valid_stopwords(self):
        """Verify valid stopwords list passes validation."""
        assert validate_extraction_config_field('stopwords', ['word1', 'word2'])
        assert validate_extraction_config_field('stopwords', [])

    def test_validate_valid_domain_vocab(self):
        """Verify valid domain vocab dict passes validation."""
        assert validate_extraction_config_field('domain_vocab', {'Type': ['term']})
        assert validate_extraction_config_field('domain_vocab', {})

    def test_validate_invalid_field_name(self):
        """Verify invalid field name raises error."""
        with pytest.raises(ValueError):
            validate_extraction_config_field('nonexistent_field', 0.5)

    def test_validate_invalid_type(self):
        """Verify invalid type fails validation."""
        # confidence_threshold should be float, not string
        assert not validate_extraction_config_field('confidence_threshold', 'invalid')


class TestTypedDictCreation:
    """Tests for creating ExtractionConfig from typed dictionaries."""

    def test_create_from_valid_typed_dict(self):
        """Verify creation from valid typed dictionary."""
        config_dict = {
            'confidence_threshold': 0.75,
            'max_entities': 1000,
            'window_size': 150,
        }
        config = create_extraction_config_from_typed_dict(config_dict)
        
        assert config.confidence_threshold == 0.75
        assert config.max_entities == 1000
        assert config.window_size == 150

    def test_create_with_domain_vocab(self):
        """Verify creation with domain vocabulary."""
        config_dict = {
            'confidence_threshold': 0.7,
            'domain_vocab': {
                'Symptom': ['fever', 'cough'],
                'Medication': ['aspirin']
            }
        }
        config = create_extraction_config_from_typed_dict(config_dict)
        
        assert 'Symptom' in config.domain_vocab
        assert 'fever' in config.domain_vocab['Symptom']

    def test_create_rejects_invalid_field(self):
        """Verify creation rejects unknown fields."""
        config_dict = {'invalid_field': 'value'}
        
        with pytest.raises(ValueError):
            create_extraction_config_from_typed_dict(config_dict)

    def test_create_rejects_wrong_type(self):
        """Verify creation rejects wrong field types."""
        config_dict = {'confidence_threshold': 'not_a_float'}
        
        with pytest.raises(TypeError):
            create_extraction_config_from_typed_dict(config_dict)

    def test_create_with_all_valid_fields(self):
        """Verify creation with all fields."""
        config_dict = {
            'confidence_threshold': 0.75,
            'max_entities': 1000,
            'max_relationships': 500,
            'window_size': 150,
            'min_entity_length': 2,
            'stopwords': ['patient'],
            'allowed_entity_types': ['Person', 'Organization'],
            'domain_vocab': {'Type': ['term']},
            'custom_rules': [(r'pattern', 'Type')],
            'llm_fallback_threshold': 0.6,
            'max_confidence': 0.95,
            'include_properties': True,
        }
        
        config = create_extraction_config_from_typed_dict(config_dict)
        
        # Verify all fields set correctly
        assert config.confidence_threshold == 0.75
        assert config.max_entities == 1000
        assert config.max_relationships == 500


class TestFieldInfo:
    """Tests for field metadata retrieval."""

    def test_get_field_info_returns_dict(self):
        """Verify field info is returned as dictionary."""
        info = get_extraction_config_field_info()
        assert isinstance(info, dict)

    def test_all_fields_have_metadata(self):
        """Verify all fields have metadata entries."""
        info = get_extraction_config_field_info()
        
        expected_fields = {
            'confidence_threshold', 'max_entities', 'max_relationships',
            'window_size', 'min_entity_length', 'stopwords',
            'allowed_entity_types', 'domain_vocab', 'custom_rules',
            'llm_fallback_threshold', 'max_confidence', 'include_properties'
        }
        
        assert set(info.keys()) == expected_fields

    def test_field_metadata_has_required_keys(self):
        """Verify each field metadata has required keys."""
        info = get_extraction_config_field_info()
        
        required_keys = {'type', 'default', 'description'}
        
        for field_name, metadata in info.items():
            for key in required_keys:
                assert key in metadata, f"{field_name} missing {key}"

    def test_confidence_threshold_metadata(self):
        """Verify confidence_threshold metadata."""
        info = get_extraction_config_field_info()
        ct_info = info['confidence_threshold']
        
        assert ct_info['type'] == float
        assert ct_info['default'] == 0.5
        assert ct_info['valid_range'] == (0.0, 1.0)
        assert len(ct_info['description']) > 0

    def test_domain_vocab_metadata(self):
        """Verify domain_vocab metadata."""
        info = get_extraction_config_field_info()
        dv_info = info['domain_vocab']
        
        # Type is Dict[str, List[str]], check for presence in string repr
        assert 'Dict' in str(dv_info['type']) or dv_info['type'] == dict
        assert dv_info['default'] == {}
        assert len(dv_info['description']) > 0

    def test_stopwords_metadata(self):
        """Verify stopwords metadata."""
        info = get_extraction_config_field_info()
        sw_info = info['stopwords']
        
        # Type checking for List[str]
        assert 'List' in str(sw_info['type']) or sw_info['type'] == list
        assert sw_info['default'] == []


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
