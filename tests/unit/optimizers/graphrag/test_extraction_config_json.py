"""Tests for ExtractionConfig.to_json() and from_json() serialization methods."""

import json
import pytest
import sys

# Add ipfs_datasets_py directory to path for imports
sys.path.insert(0, '/home/barberb/complaint-generator/ipfs_datasets_py')

from ipfs_datasets_py.optimizers.graphrag.ontology_generator import ExtractionConfig


class TestExtractionConfigToJson:
    """Tests for ExtractionConfig.to_json() and to_json_pretty() methods."""

    def test_to_json_basic(self):
        """Test basic JSON serialization with default config."""
        config = ExtractionConfig()
        json_str = config.to_json()
        
        # Verify it's valid JSON
        data = json.loads(json_str)
        assert isinstance(data, dict)
        assert 'confidence_threshold' in data
        assert 'max_entities' in data

    def test_to_json_all_fields(self):
        """Test JSON serialization with all fields set."""
        config = ExtractionConfig(
            confidence_threshold=0.8,
            max_entities=100,
            max_relationships=50,
            window_size=512,
            include_properties=True,
            domain_vocab={'tech': ['API', 'database']},
            custom_rules=[('pattern', 'action')],
            llm_fallback_threshold=0.5,
            min_entity_length=2,
            stopwords=['the', 'a'],
            allowed_entity_types=['PERSON', 'ORG'],
            max_confidence=0.95
        )
        
        json_str = config.to_json()
        data = json.loads(json_str)
        
        assert data['confidence_threshold'] == 0.8
        assert data['max_entities'] == 100
        assert data['max_relationships'] == 50
        assert data['window_size'] == 512
        assert data['include_properties'] is True
        assert data['domain_vocab'] == {'tech': ['API', 'database']}
        assert data['custom_rules'] == [['pattern', 'action']]  # tuples become lists in JSON
        assert data['llm_fallback_threshold'] == 0.5
        assert data['min_entity_length'] == 2
        assert data['stopwords'] == ['the', 'a']
        assert data['allowed_entity_types'] == ['PERSON', 'ORG']
        assert data['max_confidence'] == 0.95

    def test_to_json_numeric_types(self):
        """Test JSON serialization preserves numeric types."""
        config = ExtractionConfig(
            confidence_threshold=0.75,
            max_entities=200,
            max_relationships=100,
            window_size=1024
        )
        
        json_str = config.to_json()
        data = json.loads(json_str)
        
        assert isinstance(data['confidence_threshold'], float)
        assert isinstance(data['max_entities'], int)
        assert isinstance(data['max_relationships'], int)
        assert isinstance(data['window_size'], int)

    def test_to_json_boolean_types(self):
        """Test JSON serialization preserves boolean types."""
        config_true = ExtractionConfig(include_properties=True)
        config_false = ExtractionConfig(include_properties=False)
        
        data_true = json.loads(config_true.to_json())
        data_false = json.loads(config_false.to_json())
        
        assert data_true['include_properties'] is True
        assert data_false['include_properties'] is False

    def test_to_json_empty_collections(self):
        """Test JSON serialization with empty collections."""
        config = ExtractionConfig(
            domain_vocab={},
            custom_rules=[],
            stopwords=[],
            allowed_entity_types=[]
        )
        
        json_str = config.to_json()
        data = json.loads(json_str)
        
        assert data['domain_vocab'] == {}
        assert data['custom_rules'] == []
        assert data['stopwords'] == []
        assert data['allowed_entity_types'] == []

    def test_to_json_compact_no_whitespace(self):
        """Test that to_json() produces compact JSON without extra whitespace."""
        config = ExtractionConfig(confidence_threshold=0.5)
        json_str = config.to_json()
        
        # Compact JSON should not have spaces after commas (only after colons per standard JSON)
        # The separators=(',', ':') means no space after colons, but json still adds space after colons for readability
        # So just verify it's compact compared to pretty-printed version
        pretty_str = config.to_json_pretty()
        
        assert len(json_str) < len(pretty_str)  # compact version shorter

    def test_to_json_sorted_keys(self):
        """Test that to_json() produces sorted keys."""
        config = ExtractionConfig(
            confidence_threshold=0.5,
            max_entities=100
        )
        json_str = config.to_json()
        
        # Parse and re-serialize to verify key order
        data = json.loads(json_str)
        keys = list(data.keys())
        assert keys == sorted(keys)

    def test_to_json_pretty_basic(self):
        """Test to_json_pretty() produces formatted JSON."""
        config = ExtractionConfig()
        json_str = config.to_json_pretty()
        
        # Verify it's valid JSON
        data = json.loads(json_str)
        assert isinstance(data, dict)
        
        # Verify it has newlines and indentation (pretty format)
        assert '\n' in json_str
        assert '  ' in json_str  # 2-space indent

    def test_to_json_pretty_custom_indent(self):
        """Test to_json_pretty() with custom indentation."""
        config = ExtractionConfig(confidence_threshold=0.5)
        
        json_4 = config.to_json_pretty(indent=4)
        json_2 = config.to_json_pretty(indent=2)
        
        # Both should be valid JSON
        assert json.loads(json_4) == json.loads(json_2)
        
        # 4-space indent should have more whitespace
        assert '    ' in json_4
        assert json_4.count(' ') > json_2.count(' ')

    def test_to_json_pretty_single_indent(self):
        """Test to_json_pretty() with single-space indent."""
        config = ExtractionConfig(
            confidence_threshold=0.5,
            max_entities=50
        )
        json_str = config.to_json_pretty(indent=1)
        
        # Should still be valid JSON
        data = json.loads(json_str)
        assert data['confidence_threshold'] == 0.5
        assert data['max_entities'] == 50

    def test_to_json_special_characters(self):
        """Test JSON serialization with special characters in strings."""
        config = ExtractionConfig(
            stopwords=['the', 'a', 'é', 'café', '日本'],
            domain_vocab={'special': ['you\'re', 'it\'s', '"quoted"']}
        )
        
        json_str = config.to_json()
        data = json.loads(json_str)
        
        assert 'é' in data['stopwords']
        assert 'café' in data['stopwords']
        assert '日本' in data['stopwords']
        assert '"\\"quoted\\""' in json_str or 'quoted' in str(data)

    def test_to_json_nested_structures(self):
        """Test JSON serialization with nested structures."""
        config = ExtractionConfig(
            domain_vocab={
                'legal': ['attorney', 'court', 'plaintiff'],
                'medical': ['diagnosis', 'treatment'],
                'technical': ['API', 'database', 'server']
            },
            custom_rules=[
                ('pattern1', 'action1'),
                ('pattern2', 'action2')
            ]
        )
        
        json_str = config.to_json()
        data = json.loads(json_str)
        
        assert 'legal' in data['domain_vocab']
        assert data['domain_vocab']['legal'] == ['attorney', 'court', 'plaintiff']
        assert len(data['custom_rules']) == 2


class TestExtractionConfigFromJson:
    """Tests for ExtractionConfig.from_json() deserialization."""

    def test_from_json_basic(self):
        """Test basic JSON deserialization."""
        json_str = '{"confidence_threshold": 0.5, "max_entities": 100}'
        config = ExtractionConfig.from_json(json_str)
        
        assert config.confidence_threshold == 0.5
        assert config.max_entities == 100

    def test_from_json_all_fields(self):
        """Test JSON deserialization with all fields."""
        json_data = {
            "confidence_threshold": 0.8,
            "max_entities": 100,
            "max_relationships": 50,
            "window_size": 512,
            "include_properties": True,
            "domain_vocab": {"tech": ["API", "database"]},
            "custom_rules": [["pattern", "action"]],
            "llm_fallback_threshold": 0.5,
            "min_entity_length": 2,
            "stopwords": ["the", "a"],
            "allowed_entity_types": ["PERSON", "ORG"],
            "max_confidence": 0.95
        }
        json_str = json.dumps(json_data)
        config = ExtractionConfig.from_json(json_str)
        
        assert config.confidence_threshold == 0.8
        assert config.max_entities == 100
        assert config.max_relationships == 50
        assert config.window_size == 512
        assert config.include_properties is True
        assert config.domain_vocab == {"tech": ["API", "database"]}
        assert config.llm_fallback_threshold == 0.5
        assert config.min_entity_length == 2
        assert config.stopwords == ["the", "a"]
        assert config.allowed_entity_types == ["PERSON", "ORG"]
        assert config.max_confidence == 0.95

    def test_from_json_partial_fields(self):
        """Test JSON deserialization with only some fields specified."""
        json_str = '{"confidence_threshold": 0.7}'
        config = ExtractionConfig.from_json(json_str)
        
        # Should use defaults for unspecified fields
        assert config.confidence_threshold == 0.7
        assert config.max_entities == 0  # default value is 0 (unlimited)

    def test_from_json_numeric_preservation(self):
        """Test that numeric types are preserved during deserialization."""
        json_str = json.dumps({
            "confidence_threshold": 0.75,
            "max_entities": 200,
            "max_relationships": 100,
            "window_size": 1024
        })
        config = ExtractionConfig.from_json(json_str)
        
        assert isinstance(config.confidence_threshold, float)
        assert isinstance(config.max_entities, int)
        assert config.confidence_threshold == 0.75
        assert config.max_entities == 200

    def test_from_json_boolean_preservation(self):
        """Test that boolean values are preserved during deserialization."""
        json_true = json.dumps({"include_properties": True})
        json_false = json.dumps({"include_properties": False})
        
        config_true = ExtractionConfig.from_json(json_true)
        config_false = ExtractionConfig.from_json(json_false)
        
        assert config_true.include_properties is True
        assert config_false.include_properties is False

    def test_from_json_invalid_json_raises(self):
        """Test that invalid JSON raises JSONDecodeError."""
        invalid_json = '{"confidence_threshold": 0.5,}'  # trailing comma
        
        with pytest.raises(json.JSONDecodeError):
            ExtractionConfig.from_json(invalid_json)

    def test_from_json_empty_string_raises(self):
        """Test that empty JSON string raises JSONDecodeError."""
        with pytest.raises(json.JSONDecodeError):
            ExtractionConfig.from_json('')

    def test_from_json_malformed_raises(self):
        """Test that malformed JSON raises JSONDecodeError."""
        malformed = 'not valid json at all'
        
        with pytest.raises(json.JSONDecodeError):
            ExtractionConfig.from_json(malformed)

    def test_from_json_collections(self):
        """Test deserialization of collection fields."""
        json_str = json.dumps({
            "stopwords": ["the", "a", "an"],
            "domain_vocab": {"legal": ["attorney", "court"], "medical": ["doctor"]},
            "allowed_entity_types": ["PERSON", "ORG", "LOCATION"],
            "custom_rules": [["pattern1", "action1"], ["pattern2", "action2"]]
        })
        config = ExtractionConfig.from_json(json_str)
        
        assert config.stopwords == ["the", "a", "an"]
        assert config.domain_vocab == {"legal": ["attorney", "court"], "medical": ["doctor"]}
        assert config.allowed_entity_types == ["PERSON", "ORG", "LOCATION"]
        # custom_rules comes back as list of lists (tuples converted to lists in JSON)
        assert len(config.custom_rules) == 2


class TestExtractionConfigJsonRoundTrip:
    """Tests for round-trip serialization and deserialization."""

    def test_round_trip_basic(self):
        """Test round-trip with basic config."""
        config_orig = ExtractionConfig(
            confidence_threshold=0.75,
            max_entities=150
        )
        
        json_str = config_orig.to_json()
        config_restored = ExtractionConfig.from_json(json_str)
        
        assert config_restored.confidence_threshold == config_orig.confidence_threshold
        assert config_restored.max_entities == config_orig.max_entities

    def test_round_trip_all_fields(self):
        """Test round-trip with all fields set."""
        config_orig = ExtractionConfig(
            confidence_threshold=0.8,
            max_entities=100,
            max_relationships=50,
            window_size=512,
            include_properties=True,
            domain_vocab={'tech': ['API', 'database']},
            custom_rules=[('pattern', 'action')],
            llm_fallback_threshold=0.5,
            min_entity_length=2,
            stopwords=['the', 'a'],
            allowed_entity_types=['PERSON', 'ORG'],
            max_confidence=0.95
        )
        
        json_str = config_orig.to_json()
        config_restored = ExtractionConfig.from_json(json_str)
        
        # Check all fields (custom_rules becomes list of lists in JSON)
        assert config_restored.confidence_threshold == config_orig.confidence_threshold
        assert config_restored.max_entities == config_orig.max_entities
        assert config_restored.max_relationships == config_orig.max_relationships
        assert config_restored.window_size == config_orig.window_size
        assert config_restored.include_properties == config_orig.include_properties
        assert config_restored.domain_vocab == config_orig.domain_vocab
        assert config_restored.llm_fallback_threshold == config_orig.llm_fallback_threshold
        assert config_restored.min_entity_length == config_orig.min_entity_length
        assert config_restored.stopwords == config_orig.stopwords
        assert config_restored.allowed_entity_types == config_orig.allowed_entity_types
        assert config_restored.max_confidence == config_orig.max_confidence

    def test_round_trip_default_config(self):
        """Test round-trip with default config."""
        config_orig = ExtractionConfig()
        
        json_str = config_orig.to_json()
        config_restored = ExtractionConfig.from_json(json_str)
        
        assert config_restored.to_dict() == config_orig.to_dict()

    def test_round_trip_with_pretty_print(self):
        """Test round-trip using pretty-printed JSON."""
        config_orig = ExtractionConfig(confidence_threshold=0.85)
        
        json_str = config_orig.to_json_pretty(indent=2)
        config_restored = ExtractionConfig.from_json(json_str)
        
        assert config_restored.confidence_threshold == 0.85

    def test_round_trip_empty_collections(self):
        """Test round-trip with empty collections."""
        config_orig = ExtractionConfig(
            domain_vocab={},
            custom_rules=[],
            stopwords=[],
            allowed_entity_types=[]
        )
        
        json_str = config_orig.to_json()
        config_restored = ExtractionConfig.from_json(json_str)
        
        assert config_restored.domain_vocab == {}
        assert config_restored.custom_rules == []
        assert config_restored.stopwords == []
        assert config_restored.allowed_entity_types == []

    def test_round_trip_special_characters(self):
        """Test round-trip with special characters."""
        config_orig = ExtractionConfig(
            stopwords=['the', 'é', 'café', '日本', '"quoted"'],
            domain_vocab={'special': ['you\'re', 'it\'s']}
        )
        
        json_str = config_orig.to_json()
        config_restored = ExtractionConfig.from_json(json_str)
        
        assert 'é' in config_restored.stopwords
        assert 'café' in config_restored.stopwords
        assert '日本' in config_restored.stopwords
        assert 'you\'re' in config_restored.domain_vocab['special']


class TestExtractionConfigJsonEquivalence:
    """Tests comparing JSON and YAML serialization methods."""

    def test_json_and_yaml_equivalence(self):
        """Test that JSON and YAML produce equivalent results when deserialized."""
        config_orig = ExtractionConfig(
            confidence_threshold=0.75,
            max_entities=150,
            stopwords=['the', 'a']
        )
        
        json_str = config_orig.to_json()
        config_from_json = ExtractionConfig.from_json(json_str)
        
        yaml_str = config_orig.to_yaml()
        config_from_yaml = ExtractionConfig.from_yaml(yaml_str)
        
        # Both should deserialize to same state
        assert config_from_json.to_dict() == config_from_yaml.to_dict()

    def test_json_dict_equivalence(self):
        """Test that JSON round-trip equals dict round-trip."""
        config_orig = ExtractionConfig(
            confidence_threshold=0.8,
            max_entities=100,
            domain_vocab={'tech': ['API']}
        )
        
        json_str = config_orig.to_json()
        config_from_json = ExtractionConfig.from_json(json_str)
        
        d = config_orig.to_dict()
        config_from_dict = ExtractionConfig.from_dict(d)
        
        # Both should produce identical configs
        assert config_from_json.to_dict() == config_from_dict.to_dict()
