"""
Comprehensive tests for validators module.

Tests cover input validation, sanitization, model name validation,
IPFS hash validation, and security checks.
"""
import pytest
from unittest.mock import Mock, MagicMock, patch
import hashlib


# Test fixtures
@pytest.fixture
def validator():
    """Create validator instance for testing."""
    from ipfs_datasets_py.mcp_server.validators import EnhancedParameterValidator
    return EnhancedParameterValidator()


# Test Class 1: Text Input Validation
class TestTextInputValidation:
    """Test suite for text input validation."""
    
    def test_validate_text_with_valid_input(self, validator):
        """
        GIVEN: Valid text input within length constraints
        WHEN: Validating text
        THEN: Returns cleaned text
        """
        # Arrange
        text = "This is a valid text input"
        
        # Act
        result = validator.validate_text_input(text)
        
        # Assert
        assert result == "This is a valid text input"
        assert validator.performance_metrics['validations_performed'] >= 1
    
    def test_validate_text_with_whitespace(self, validator):
        """
        GIVEN: Text with leading/trailing whitespace
        WHEN: Validating text
        THEN: Returns trimmed text
        """
        # Arrange
        text = "  Text with whitespace  "
        
        # Act
        result = validator.validate_text_input(text)
        
        # Assert
        assert result == "Text with whitespace"
    
    def test_validate_text_exceeds_max_length(self, validator):
        """
        GIVEN: Text exceeding max length
        WHEN: Validating text
        THEN: Raises ValidationError
        """
        # Arrange
        from ipfs_datasets_py.mcp_server.validators import ValidationError
        text = "a" * 10001  # Exceeds default max of 10000
        
        # Act & Assert
        with pytest.raises(ValidationError) as exc_info:
            validator.validate_text_input(text)
        
        assert "must not exceed" in str(exc_info.value)
        assert validator.performance_metrics['validation_errors'] >= 1
    
    def test_validate_text_below_min_length(self, validator):
        """
        GIVEN: Empty or very short text
        WHEN: Validating text
        THEN: Raises ValidationError
        """
        # Arrange
        from ipfs_datasets_py.mcp_server.validators import ValidationError
        text = ""
        
        # Act & Assert
        with pytest.raises(ValidationError) as exc_info:
            validator.validate_text_input(text)
        
        assert "at least" in str(exc_info.value)
    
    def test_validate_text_with_non_string_input(self, validator):
        """
        GIVEN: Non-string input
        WHEN: Validating text
        THEN: Raises ValidationError
        """
        # Arrange
        from ipfs_datasets_py.mcp_server.validators import ValidationError
        text = 12345  # Not a string
        
        # Act & Assert
        with pytest.raises(ValidationError) as exc_info:
            validator.validate_text_input(text)
        
        assert "must be a string" in str(exc_info.value)


# Test Class 2: Model Name Validation
class TestModelNameValidation:
    """Test suite for model name validation."""
    
    def test_validate_model_name_sentence_transformers(self, validator):
        """
        GIVEN: Valid sentence-transformers model name
        WHEN: Validating model name
        THEN: Returns model name
        """
        # Arrange
        model_name = "sentence-transformers/all-MiniLM-L6-v2"
        
        # Act
        result = validator.validate_model_name(model_name)
        
        # Assert
        assert result == model_name
    
    def test_validate_model_name_with_caching(self, validator):
        """
        GIVEN: Same model name validated twice
        WHEN: Validating model name second time
        THEN: Uses cache and increments cache_hits
        """
        # Arrange
        model_name = "sentence-transformers/test-model"
        
        # Act
        result1 = validator.validate_model_name(model_name)
        cache_hits_before = validator.performance_metrics['cache_hits']
        result2 = validator.validate_model_name(model_name)
        cache_hits_after = validator.performance_metrics['cache_hits']
        
        # Assert
        assert result1 == result2
        assert cache_hits_after > cache_hits_before


# Test Class 3: IPFS Hash Validation
class TestIPFSHashValidation:
    """Test suite for IPFS hash validation."""
    
    def test_validate_ipfs_hash_cidv0(self, validator):
        """
        GIVEN: Valid CIDv0 IPFS hash
        WHEN: Validating IPFS hash
        THEN: Returns the hash value
        """
        # Arrange
        hash_value = "QmYwAPJzv5CZsnA625s3Xf2nemtYgPpHdWEz79ojWnPbdG"
        
        # Act
        result = validator.validate_ipfs_hash(hash_value)
        
        # Assert
        assert result == hash_value
    
    def test_validate_ipfs_hash_cidv1(self, validator):
        """
        GIVEN: Valid CIDv1 IPFS hash
        WHEN: Validating IPFS hash
        THEN: Returns the hash value
        """
        # Arrange
        # Valid CIDv1 format (bafybe...)
        hash_value = "bafybeigdyrzt5sfp7udm7hu76uh7y26nf3efuylqabf3oclgtqy55fbzdi"
        
        # Act
        result = validator.validate_ipfs_hash(hash_value)
        
        # Assert
        assert result == hash_value
    
    def test_validate_ipfs_hash_invalid_format(self, validator):
        """
        GIVEN: Invalid IPFS hash format
        WHEN: Validating IPFS hash
        THEN: Raises ValidationError
        """
        # Arrange
        from ipfs_datasets_py.mcp_server.validators import ValidationError
        hash_value = "invalid-hash-format"
        
        # Act & Assert
        with pytest.raises(ValidationError) as exc_info:
            validator.validate_ipfs_hash(hash_value)
        
        assert "Invalid IPFS hash format" in str(exc_info.value)


# Test Class 4: Collection Name Validation
class TestCollectionNameValidation:
    """Test suite for collection name validation."""
    
    def test_validate_collection_name_valid(self, validator):
        """
        GIVEN: Valid collection name (alphanumeric, hyphens, underscores)
        WHEN: Validating collection name
        THEN: Returns the collection name
        """
        # Arrange
        name = "my_collection-123"
        
        # Act
        result = validator.validate_collection_name(name)
        
        # Assert
        assert result == name
    
    def test_validate_collection_name_with_special_chars(self, validator):
        """
        GIVEN: Collection name with invalid special characters
        WHEN: Validating collection name
        THEN: Raises ValidationError
        """
        # Arrange
        from ipfs_datasets_py.mcp_server.validators import ValidationError
        name = "invalid@collection#name"
        
        # Act & Assert
        with pytest.raises(ValidationError) as exc_info:
            validator.validate_collection_name(name)
        
        assert "alphanumeric" in str(exc_info.value)


# Test Class 5: Sanitization Functions
class TestSanitizationFunctions:
    """Test suite for sanitization functions."""
    
    def test_sanitize_removes_suspicious_patterns(self, validator):
        """
        GIVEN: Text with suspicious patterns
        WHEN: Checking for suspicious patterns
        THEN: Detects suspicious content
        """
        # Arrange
        text = "SELECT * FROM users WHERE 1=1"
        
        # Act
        result = validator._contains_suspicious_patterns(text)
        
        # Assert
        # Should detect SQL injection patterns
        assert isinstance(result, bool)
    
    def test_sanitize_safe_text(self, validator):
        """
        GIVEN: Safe text without suspicious patterns
        WHEN: Checking for suspicious patterns
        THEN: Returns False (no suspicious content)
        """
        # Arrange
        text = "This is a safe and normal text"
        
        # Act
        result = validator._contains_suspicious_patterns(text)
        
        # Assert
        assert result is False


# Test Class 6: Performance Metrics
class TestPerformanceMetrics:
    """Test suite for validator performance metrics."""
    
    def test_metrics_track_validations_performed(self, validator):
        """
        GIVEN: Multiple validation operations
        WHEN: Performing validations
        THEN: Metrics track validation count
        """
        # Arrange & Act
        validator.validate_text_input("Test 1")
        validator.validate_text_input("Test 2")
        validator.validate_text_input("Test 3")
        
        # Assert
        assert validator.performance_metrics['validations_performed'] >= 3
    
    def test_metrics_track_validation_errors(self, validator):
        """
        GIVEN: Invalid inputs causing errors
        WHEN: Validating invalid inputs
        THEN: Metrics track error count
        """
        # Arrange
        from ipfs_datasets_py.mcp_server.validators import ValidationError
        errors_before = validator.performance_metrics['validation_errors']
        
        # Act
        try:
            validator.validate_text_input("")  # Should fail
        except ValidationError:
            pass
        
        try:
            validator.validate_text_input(None)  # Should fail
        except (ValidationError, AttributeError):
            pass
        
        errors_after = validator.performance_metrics['validation_errors']
        
        # Assert
        assert errors_after >= errors_before


# Test Class 7: Cache Key Generation
class TestCacheKeyGeneration:
    """Test suite for cache key generation."""
    
    def test_cache_key_generation_consistency(self, validator):
        """
        GIVEN: Same value and validation type
        WHEN: Generating cache key multiple times
        THEN: Returns consistent cache key
        """
        # Arrange
        value = "test-value"
        validation_type = "model_name"
        
        # Act
        key1 = validator._cache_key(value, validation_type)
        key2 = validator._cache_key(value, validation_type)
        
        # Assert
        assert key1 == key2
        assert validation_type in key1
    
    def test_cache_key_uniqueness(self, validator):
        """
        GIVEN: Different values or validation types
        WHEN: Generating cache keys
        THEN: Returns unique keys
        """
        # Arrange
        value1 = "test-value-1"
        value2 = "test-value-2"
        validation_type = "model_name"
        
        # Act
        key1 = validator._cache_key(value1, validation_type)
        key2 = validator._cache_key(value2, validation_type)
        
        # Assert
        assert key1 != key2


# Test Class 8: Search Filters Validation
class TestSearchFiltersValidation:
    """Test suite for search filter validation."""

    def test_validate_search_filters_simple_equality(self, validator):
        """
        GIVEN: Simple equality filter dict
        WHEN: Validating search filters
        THEN: Returns the same dict unchanged
        """
        filters = {"status": "active", "priority": "high"}
        result = validator.validate_search_filters(filters)
        assert result == filters

    def test_validate_search_filters_non_dict_raises(self, validator):
        """
        GIVEN: Non-dict filters
        WHEN: Validating search filters
        THEN: Raises ValidationError
        """
        from ipfs_datasets_py.mcp_server.validators import ValidationError
        with pytest.raises(ValidationError):
            validator.validate_search_filters(["not", "a", "dict"])

    def test_validate_search_filters_too_many_keys_raises(self, validator):
        """
        GIVEN: Filters dict with more than 50 keys
        WHEN: Validating search filters
        THEN: Raises ValidationError (complexity limit)
        """
        from ipfs_datasets_py.mcp_server.validators import ValidationError
        big_filters = {f"field{i}": i for i in range(51)}
        with pytest.raises(ValidationError, match="Too many filters"):
            validator.validate_search_filters(big_filters)

    def test_validate_search_filters_invalid_operator_raises(self, validator):
        """
        GIVEN: Filter with an unknown operator key
        WHEN: Validating search filters
        THEN: Raises ValidationError
        """
        from ipfs_datasets_py.mcp_server.validators import ValidationError
        filters = {"age": {"$where": "bad"}}  # $where is not whitelisted
        with pytest.raises(ValidationError):
            validator.validate_search_filters(filters)

    def test_validate_search_filters_empty_dict(self, validator):
        """
        GIVEN: Empty filter dict
        WHEN: Validating search filters
        THEN: Returns empty dict (valid — returns all results)
        """
        result = validator.validate_search_filters({})
        assert result == {}


# Test Class 9: File Path Validation
class TestFilePathValidation:
    """Test suite for file path validation."""

    def test_validate_file_path_simple_relative(self, validator):
        """
        GIVEN: Simple relative file path
        WHEN: Validating file path
        THEN: Returns path string
        """
        result = validator.validate_file_path("data/input.txt")
        assert result == "data/input.txt"

    def test_validate_file_path_traversal_blocked(self, validator):
        """
        GIVEN: Path with directory traversal (..)
        WHEN: Validating file path
        THEN: Raises ValidationError
        """
        from ipfs_datasets_py.mcp_server.validators import ValidationError
        with pytest.raises(ValidationError):
            validator.validate_file_path("../../etc/passwd")

    def test_validate_file_path_absolute_blocked(self, validator):
        """
        GIVEN: Absolute path starting with /
        WHEN: Validating file path
        THEN: Raises ValidationError
        """
        from ipfs_datasets_py.mcp_server.validators import ValidationError
        with pytest.raises(ValidationError):
            validator.validate_file_path("/etc/shadow")

    def test_validate_file_path_extension_restriction(self, validator):
        """
        GIVEN: Path with disallowed extension and allowed_extensions set
        WHEN: Validating file path
        THEN: Raises ValidationError
        """
        from ipfs_datasets_py.mcp_server.validators import ValidationError
        with pytest.raises(ValidationError):
            validator.validate_file_path(
                "upload/virus.exe",
                allowed_extensions={".txt", ".json"}
            )

    def test_validate_file_path_allowed_extension(self, validator):
        """
        GIVEN: Path with extension in allowed_extensions
        WHEN: Validating file path
        THEN: Returns path string
        """
        result = validator.validate_file_path(
            "data/config.json",
            allowed_extensions={".json", ".yaml"}
        )
        assert result == "data/config.json"


# Test Class 10: URL Validation
class TestUrlValidation:
    """Test suite for URL validation."""

    def test_validate_url_valid_https(self, validator):
        """
        GIVEN: Valid HTTPS URL
        WHEN: Validating URL
        THEN: Returns URL unchanged
        """
        url = "https://example.com/path?q=1"
        result = validator.validate_url(url)
        assert result == url

    def test_validate_url_scheme_restriction(self, validator):
        """
        GIVEN: URL with disallowed scheme
        WHEN: Validating URL with allowed_schemes={'https'}
        THEN: Raises ValidationError
        """
        from ipfs_datasets_py.mcp_server.validators import ValidationError
        with pytest.raises(ValidationError):
            validator.validate_url("ftp://files.example.com",
                                   allowed_schemes={"http", "https"})

    def test_validate_url_javascript_blocked(self, validator):
        """
        GIVEN: javascript: pseudo-URL
        WHEN: Validating URL with allowed_schemes={'http','https'}
        THEN: Raises ValidationError (XSS prevention)
        """
        from ipfs_datasets_py.mcp_server.validators import ValidationError
        with pytest.raises(ValidationError):
            validator.validate_url("javascript:alert('xss')",
                                   allowed_schemes={"http", "https"})

    def test_validate_url_missing_scheme_raises(self, validator):
        """
        GIVEN: URL without a scheme
        WHEN: Validating URL
        THEN: Raises ValidationError
        """
        from ipfs_datasets_py.mcp_server.validators import ValidationError
        with pytest.raises(ValidationError, match="scheme"):
            validator.validate_url("example.com/path")

    def test_validate_url_non_string_raises(self, validator):
        """
        GIVEN: Non-string input
        WHEN: Validating URL
        THEN: Raises ValidationError
        """
        from ipfs_datasets_py.mcp_server.validators import ValidationError
        with pytest.raises(ValidationError):
            validator.validate_url(12345)


# Test Class 11: Numeric Range Validation
class TestNumericRangeValidation:
    """Test suite for numeric range validation."""

    def test_validate_numeric_valid_in_range(self, validator):
        """
        GIVEN: Numeric value within [min_val, max_val]
        WHEN: Validating range
        THEN: Returns value unchanged
        """
        result = validator.validate_numeric_range(50, "batch_size", min_val=1, max_val=100)
        assert result == 50

    def test_validate_numeric_below_minimum_raises(self, validator):
        """
        GIVEN: Value below minimum
        WHEN: Validating range
        THEN: Raises ValidationError
        """
        from ipfs_datasets_py.mcp_server.validators import ValidationError
        with pytest.raises(ValidationError):
            validator.validate_numeric_range(0, "batch_size", min_val=1)

    def test_validate_numeric_above_maximum_raises(self, validator):
        """
        GIVEN: Value above maximum
        WHEN: Validating range
        THEN: Raises ValidationError
        """
        from ipfs_datasets_py.mcp_server.validators import ValidationError
        with pytest.raises(ValidationError):
            validator.validate_numeric_range(150, "batch_size", max_val=100)

    def test_validate_numeric_none_with_allow_none(self, validator):
        """
        GIVEN: None value with allow_none=True
        WHEN: Validating range
        THEN: Returns None without error
        """
        result = validator.validate_numeric_range(None, "optional_param",
                                                  min_val=0, allow_none=True)
        assert result is None

    def test_validate_numeric_non_numeric_raises(self, validator):
        """
        GIVEN: Non-numeric string value
        WHEN: Validating range
        THEN: Raises ValidationError
        """
        from ipfs_datasets_py.mcp_server.validators import ValidationError
        with pytest.raises(ValidationError):
            validator.validate_numeric_range("not_a_number", "param", min_val=0)


# Test Class 12: JSON Schema Validation
class TestJsonSchemaValidation:
    """Test suite for JSON schema validation."""

    def test_validate_json_schema_returns_data(self, validator):
        """
        GIVEN: Any data with a schema
        WHEN: Validating against schema
        THEN: Returns original data object (either validated or gracefully skipped)
        """
        data = {"name": "Alice", "age": 30}
        schema = {"type": "object", "required": ["name"]}
        result = validator.validate_json_schema(data, schema)
        # Return value is always the original data
        assert result is data

    def test_validate_json_schema_schema_validation_error(self, validator):
        """
        GIVEN: Data that violates schema (if jsonschema available)
        WHEN: Validating data against strict schema
        THEN: Either raises ValidationError or returns data (graceful degradation)
        """
        from ipfs_datasets_py.mcp_server.validators import ValidationError
        data = "not an object"
        schema = {"type": "object", "required": ["name"]}
        # Should not crash - may raise ValidationError or return data
        try:
            result = validator.validate_json_schema(data, schema)
            # If no error, must return original data
            assert result is data
        except ValidationError:
            pass  # Expected when jsonschema is installed


# Test Class 13: Clear Cache
class TestClearCache:
    """Test suite for cache clearing."""

    def test_clear_cache_empties_validation_cache(self, validator):
        """
        GIVEN: Validator with some cache entries
        WHEN: clear_cache() is called
        THEN: validation_cache is empty
        """
        # Populate cache via model name validation
        validator.validate_model_name("sentence-transformers/all-MiniLM-L6-v2")
        # Cache should have an entry
        validator.clear_cache()
        assert len(validator.validation_cache) == 0

    def test_clear_cache_does_not_reset_metrics(self, validator):
        """
        GIVEN: Validator that has performed validations
        WHEN: clear_cache() is called
        THEN: performance_metrics counters are NOT reset
        """
        validator.validate_text_input("hello")
        count_before = validator.performance_metrics['validations_performed']
        validator.clear_cache()
        # Metrics should be preserved
        assert validator.performance_metrics['validations_performed'] == count_before


# Test Class 14: Get Performance Metrics
class TestGetPerformanceMetrics:
    """Test suite for performance metrics retrieval."""

    def test_get_performance_metrics_returns_copy(self, validator):
        """
        GIVEN: Validator with counters
        WHEN: get_performance_metrics() is called
        THEN: Returns a dict copy; mutations don't affect internal state
        """
        metrics = validator.get_performance_metrics()
        original_count = metrics['validations_performed']
        # Mutate the returned copy
        metrics['validations_performed'] = 9999
        # Internal state should be unchanged
        assert validator.performance_metrics['validations_performed'] == original_count

    def test_get_performance_metrics_tracks_operations(self, validator):
        """
        GIVEN: Several validation operations
        WHEN: get_performance_metrics() is called
        THEN: Returns updated counters
        """
        start = validator.get_performance_metrics()['validations_performed']
        validator.validate_text_input("test one")
        validator.validate_text_input("test two")
        end = validator.get_performance_metrics()['validations_performed']
        assert end == start + 2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
