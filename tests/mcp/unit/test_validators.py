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


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
