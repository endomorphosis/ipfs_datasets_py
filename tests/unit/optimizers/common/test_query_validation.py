"""
Tests for QueryValidationMixin

Ensures all validation methods work correctly with various inputs.
"""

import pytest
import time
import logging
from typing import Any, Dict, List

from ipfs_datasets_py.optimizers.common.query_validation import QueryValidationMixin


# Test class that uses the mixin
class TestOptimizer(QueryValidationMixin):
    """Test optimizer class with QueryValidationMixin."""
    
    def __init__(self, cache_enabled=True, cache_ttl=300.0):
        self.cache_enabled = cache_enabled
        self.cache_ttl = cache_ttl
        self.query_cache = {}
        self.logger = logging.getLogger(__name__)


class TestNumericParamValidation:
    """Test numeric parameter validation."""
    
    def test_valid_integer(self):
        """Test validation of valid integer."""
        optimizer = TestOptimizer()
        result = optimizer.validate_numeric_param(5, 'test_param', min_value=1, max_value=10)
        assert result == 5
    
    def test_valid_float(self):
        """Test validation of valid float."""
        optimizer = TestOptimizer()
        result = optimizer.validate_numeric_param(5.5, 'test_param', min_value=1.0, max_value=10.0)
        assert result == 5.5
    
    def test_none_with_default(self):
        """Test None value returns default."""
        optimizer = TestOptimizer()
        result = optimizer.validate_numeric_param(None, 'test_param', default=7)
        assert result == 7
    
    def test_none_allowed(self):
        """Test None value when allowed."""
        optimizer = TestOptimizer()
        result = optimizer.validate_numeric_param(None, 'test_param', allow_none=True)
        assert result is None
    
    def test_below_minimum(self):
        """Test value below minimum is clamped."""
        optimizer = TestOptimizer()
        result = optimizer.validate_numeric_param(0, 'test_param', min_value=1, max_value=10)
        assert result == 1
    
    def test_above_maximum(self):
        """Test value above maximum is clamped."""
        optimizer = TestOptimizer()
        result = optimizer.validate_numeric_param(15, 'test_param', min_value=1, max_value=10)
        assert result == 10
    
    def test_string_conversion(self):
        """Test string to numeric conversion."""
        optimizer = TestOptimizer()
        result = optimizer.validate_numeric_param("5", 'test_param', default=0)
        assert result == 5.0
    
    def test_invalid_type_returns_default(self):
        """Test invalid type returns default."""
        optimizer = TestOptimizer()
        result = optimizer.validate_numeric_param("invalid", 'test_param', default=10)
        assert result == 10


class TestListParamValidation:
    """Test list parameter validation."""
    
    def test_valid_list(self):
        """Test validation of valid list."""
        optimizer = TestOptimizer()
        result = optimizer.validate_list_param([1, 2, 3], 'test_param')
        assert result == [1, 2, 3]
    
    def test_tuple_converted_to_list(self):
        """Test tuple is converted to list."""
        optimizer = TestOptimizer()
        result = optimizer.validate_list_param((1, 2, 3), 'test_param')
        assert result == [1, 2, 3]
        assert isinstance(result, list)
    
    def test_none_returns_default(self):
        """Test None returns default."""
        optimizer = TestOptimizer()
        result = optimizer.validate_list_param(None, 'test_param', default=[1, 2])
        assert result == [1, 2]
    
    def test_none_allowed(self):
        """Test None when allowed."""
        optimizer = TestOptimizer()
        result = optimizer.validate_list_param(None, 'test_param', allow_none=True)
        assert result is None
    
    def test_element_type_validation(self):
        """Test element type validation."""
        optimizer = TestOptimizer()
        result = optimizer.validate_list_param(
            [1, "2", 3], 
            'test_param', 
            element_type=int
        )
        assert result == [1, 2, 3]
    
    def test_element_type_filtering(self):
        """Test invalid elements are filtered."""
        optimizer = TestOptimizer()
        result = optimizer.validate_list_param(
            [1, "invalid", 3], 
            'test_param', 
            element_type=int
        )
        assert result == [1, 3]
    
    def test_minimum_length(self):
        """Test minimum length validation."""
        optimizer = TestOptimizer()
        result = optimizer.validate_list_param(
            [1, 2], 
            'test_param', 
            min_length=3,
            default=[1, 2, 3, 4]
        )
        assert result == [1, 2, 3, 4]
    
    def test_maximum_length(self):
        """Test maximum length truncation."""
        optimizer = TestOptimizer()
        result = optimizer.validate_list_param(
            [1, 2, 3, 4, 5], 
            'test_param', 
            max_length=3
        )
        assert result == [1, 2, 3]
    
    def test_invalid_type_returns_default(self):
        """Test invalid type returns default."""
        optimizer = TestOptimizer()
        result = optimizer.validate_list_param(
            "not a list", 
            'test_param', 
            default=[1, 2]
        )
        assert result == [1, 2]


class TestStringParamValidation:
    """Test string parameter validation."""
    
    def test_valid_string(self):
        """Test validation of valid string."""
        optimizer = TestOptimizer()
        result = optimizer.validate_string_param("test", 'test_param')
        assert result == "test"
    
    def test_none_returns_default(self):
        """Test None returns default."""
        optimizer = TestOptimizer()
        result = optimizer.validate_string_param(None, 'test_param', default="default")
        assert result == "default"
    
    def test_none_allowed(self):
        """Test None when allowed."""
        optimizer = TestOptimizer()
        result = optimizer.validate_string_param(None, 'test_param', allow_none=True)
        assert result is None
    
    def test_number_to_string_conversion(self):
        """Test number is converted to string."""
        optimizer = TestOptimizer()
        result = optimizer.validate_string_param(42, 'test_param')
        assert result == "42"
        assert isinstance(result, str)
    
    def test_allowed_values_valid(self):
        """Test allowed values validation with valid value."""
        optimizer = TestOptimizer()
        result = optimizer.validate_string_param(
            "wikipedia", 
            'graph_type',
            allowed_values=['wikipedia', 'ipld', 'general']
        )
        assert result == "wikipedia"
    
    def test_allowed_values_invalid(self):
        """Test allowed values validation with invalid value."""
        optimizer = TestOptimizer()
        result = optimizer.validate_string_param(
            "invalid", 
            'graph_type',
            allowed_values=['wikipedia', 'ipld', 'general'],
            default="general"
        )
        assert result == "general"
    
    def test_case_insensitive_allowed_values(self):
        """Test case-insensitive allowed values."""
        optimizer = TestOptimizer()
        result = optimizer.validate_string_param(
            "WIKIPEDIA", 
            'graph_type',
            allowed_values=['wikipedia', 'ipld', 'general'],
            case_sensitive=False,
            default="general"
        )
        # Should accept as valid (case-insensitive)
        assert result == "WIKIPEDIA"


class TestCacheValidation:
    """Test cache validation methods."""
    
    def test_validate_cache_enabled_true(self):
        """Test cache enabled returns True."""
        optimizer = TestOptimizer(cache_enabled=True)
        assert optimizer.validate_cache_enabled() is True
    
    def test_validate_cache_enabled_false(self):
        """Test cache disabled returns False."""
        optimizer = TestOptimizer(cache_enabled=False)
        assert optimizer.validate_cache_enabled() is False
    
    def test_validate_cache_enabled_no_attribute(self):
        """Test missing cache_enabled attribute returns False."""
        class NoCache(QueryValidationMixin):
            pass
        optimizer = NoCache()
        assert optimizer.validate_cache_enabled() is False
    
    def test_validate_cache_entry_valid(self):
        """Test valid cache entry."""
        optimizer = TestOptimizer()
        cache_key = "test_key"
        optimizer.query_cache[cache_key] = ("result", time.time())
        
        assert optimizer.validate_cache_entry(cache_key) is True
    
    def test_validate_cache_entry_missing(self):
        """Test missing cache entry."""
        optimizer = TestOptimizer()
        assert optimizer.validate_cache_entry("missing_key") is False
    
    def test_validate_cache_entry_expired(self):
        """Test expired cache entry."""
        optimizer = TestOptimizer(cache_ttl=1.0)
        cache_key = "test_key"
        optimizer.query_cache[cache_key] = ("result", time.time() - 2.0)
        
        assert optimizer.validate_cache_entry(cache_key) is False
        # Should also remove expired entry
        assert cache_key not in optimizer.query_cache
    
    def test_validate_cache_entry_invalid_structure(self):
        """Test invalid cache entry structure."""
        optimizer = TestOptimizer()
        cache_key = "test_key"
        optimizer.query_cache[cache_key] = "invalid_structure"
        
        assert optimizer.validate_cache_entry(cache_key) is False
        # Should remove invalid entry
        assert cache_key not in optimizer.query_cache
    
    def test_validate_cache_entry_invalid_timestamp(self):
        """Test invalid timestamp in cache entry."""
        optimizer = TestOptimizer()
        cache_key = "test_key"
        optimizer.query_cache[cache_key] = ("result", "invalid_timestamp")
        
        assert optimizer.validate_cache_entry(cache_key) is False
        # Should remove invalid entry
        assert cache_key not in optimizer.query_cache
    
    def test_validate_cache_entry_skip_expiration_check(self):
        """Test skipping expiration check."""
        optimizer = TestOptimizer(cache_ttl=1.0)
        cache_key = "test_key"
        optimizer.query_cache[cache_key] = ("result", time.time() - 2.0)
        
        assert optimizer.validate_cache_entry(cache_key, check_expiration=False) is True
    
    def test_generate_cache_key_simple(self):
        """Test generating cache key from simple arguments."""
        optimizer = TestOptimizer()
        key1 = optimizer.generate_cache_key("arg1", "arg2", param1="value1")
        key2 = optimizer.generate_cache_key("arg1", "arg2", param1="value1")
        
        assert key1 == key2  # Same inputs should produce same key
        assert isinstance(key1, str)
        assert len(key1) == 64  # SHA256 hash length
    
    def test_generate_cache_key_different_args(self):
        """Test different arguments produce different keys."""
        optimizer = TestOptimizer()
        key1 = optimizer.generate_cache_key("arg1", "arg2")
        key2 = optimizer.generate_cache_key("arg1", "arg3")
        
        assert key1 != key2
    
    def test_generate_cache_key_with_class_name(self):
        """Test cache key with class name."""
        optimizer = TestOptimizer()
        key1 = optimizer.generate_cache_key("arg1", include_class_name=True)
        key2 = optimizer.generate_cache_key("arg1", include_class_name=False)
        
        assert key1 != key2


class TestQueryStructureValidation:
    """Test query structure validation methods."""
    
    def test_validate_query_structure_valid(self):
        """Test valid query structure."""
        optimizer = TestOptimizer()
        query = {"vector": [1, 2, 3], "max_results": 10}
        
        assert optimizer.validate_query_structure(query) is True
    
    def test_validate_query_structure_invalid_type(self):
        """Test invalid query type."""
        optimizer = TestOptimizer()
        assert optimizer.validate_query_structure("not a dict") is False
    
    def test_validate_query_structure_missing_required_fields(self):
        """Test missing required fields."""
        optimizer = TestOptimizer()
        query = {"vector": [1, 2, 3]}
        
        assert optimizer.validate_query_structure(
            query, 
            required_fields=['vector', 'max_results']
        ) is False
    
    def test_validate_query_structure_has_required_fields(self):
        """Test query with all required fields."""
        optimizer = TestOptimizer()
        query = {"vector": [1, 2, 3], "max_results": 10}
        
        assert optimizer.validate_query_structure(
            query, 
            required_fields=['vector', 'max_results']
        ) is True
    
    def test_ensure_query_defaults_empty_query(self):
        """Test ensuring defaults on empty query."""
        optimizer = TestOptimizer()
        query = {}
        defaults = {'max_depth': 2, 'max_results': 10}
        
        result = optimizer.ensure_query_defaults(query, defaults)
        
        assert result['max_depth'] == 2
        assert result['max_results'] == 10
    
    def test_ensure_query_defaults_partial_query(self):
        """Test ensuring defaults on partial query."""
        optimizer = TestOptimizer()
        query = {'max_depth': 5}
        defaults = {'max_depth': 2, 'max_results': 10}
        
        result = optimizer.ensure_query_defaults(query, defaults)
        
        assert result['max_depth'] == 5  # Existing value preserved
        assert result['max_results'] == 10  # Default added
    
    def test_ensure_query_defaults_invalid_query(self):
        """Test ensuring defaults on invalid query."""
        optimizer = TestOptimizer()
        query = "not a dict"
        defaults = {'max_depth': 2}
        
        result = optimizer.ensure_query_defaults(query, defaults)
        
        assert isinstance(result, dict)
        assert result['max_depth'] == 2
    
    def test_ensure_nested_dict_creates_structure(self):
        """Test creating nested dictionary structure."""
        optimizer = TestOptimizer()
        query = {}
        
        result = optimizer.ensure_nested_dict(
            query, 
            'traversal', 
            'max_depth', 
            default_value=2
        )
        
        assert 'traversal' in result
        assert 'max_depth' in result['traversal']
        assert result['traversal']['max_depth'] == 2
    
    def test_ensure_nested_dict_preserves_existing(self):
        """Test preserving existing nested values."""
        optimizer = TestOptimizer()
        query = {'traversal': {'max_depth': 5}}
        
        result = optimizer.ensure_nested_dict(
            query, 
            'traversal', 
            'max_depth', 
            default_value=2
        )
        
        assert result['traversal']['max_depth'] == 5  # Existing value preserved
    
    def test_ensure_nested_dict_fixes_invalid_intermediate(self):
        """Test fixing invalid intermediate value."""
        optimizer = TestOptimizer()
        query = {'traversal': "not a dict"}
        
        result = optimizer.ensure_nested_dict(
            query, 
            'traversal', 
            'max_depth', 
            default_value=2
        )
        
        assert isinstance(result['traversal'], dict)
        assert result['traversal']['max_depth'] == 2


class TestResultValidation:
    """Test result validation methods."""
    
    def test_validate_result_for_caching_valid(self):
        """Test valid result for caching."""
        optimizer = TestOptimizer()
        result = {"data": [1, 2, 3]}
        
        assert optimizer.validate_result_for_caching(result) is True
    
    def test_validate_result_for_caching_none_not_allowed(self):
        """Test None result when not allowed."""
        optimizer = TestOptimizer()
        assert optimizer.validate_result_for_caching(None, allow_none=False) is False
    
    def test_validate_result_for_caching_none_allowed(self):
        """Test None result when allowed."""
        optimizer = TestOptimizer()
        assert optimizer.validate_result_for_caching(None, allow_none=True) is True
    
    def test_sanitize_for_cache_basic_types(self):
        """Test sanitizing basic types."""
        optimizer = TestOptimizer()
        
        assert optimizer.sanitize_for_cache(None) is None
        assert optimizer.sanitize_for_cache(42) == 42
        assert optimizer.sanitize_for_cache("test") == "test"
        assert optimizer.sanitize_for_cache(True) is True
    
    def test_sanitize_for_cache_dict(self):
        """Test sanitizing dictionary."""
        optimizer = TestOptimizer()
        data = {"a": 1, "b": {"c": 2}}
        
        result = optimizer.sanitize_for_cache(data)
        
        assert result == {"a": 1, "b": {"c": 2}}
    
    def test_sanitize_for_cache_list(self):
        """Test sanitizing list."""
        optimizer = TestOptimizer()
        data = [1, 2, [3, 4]]
        
        result = optimizer.sanitize_for_cache(data)
        
        assert result == [1, 2, [3, 4]]
    
    def test_sanitize_for_cache_numpy_array(self):
        """Test sanitizing numpy array (mock)."""
        optimizer = TestOptimizer()
        
        # Create mock numpy array
        class MockArray:
            def tolist(self):
                return [1, 2, 3]
        
        mock_array = MockArray()
        result = optimizer.sanitize_for_cache(mock_array)
        
        assert result == [1, 2, 3]
    
    def test_sanitize_for_cache_nested_with_arrays(self):
        """Test sanitizing nested structure with arrays."""
        optimizer = TestOptimizer()
        
        class MockArray:
            def tolist(self):
                return [1, 2, 3]
        
        data = {
            "vectors": [MockArray(), MockArray()],
            "metadata": {"count": 2}
        }
        
        result = optimizer.sanitize_for_cache(data)
        
        assert result["vectors"] == [[1, 2, 3], [1, 2, 3]]
        assert result["metadata"]["count"] == 2


class TestIntegration:
    """Integration tests for QueryValidationMixin."""
    
    def test_typical_query_validation_workflow(self):
        """Test typical query validation workflow."""
        optimizer = TestOptimizer()
        
        # 1. Validate and fix query structure
        query = {"vector": [1, 2, 3]}
        query = optimizer.ensure_query_defaults(query, {
            'max_depth': 2,
            'max_results': 10,
            'min_similarity': 0.5
        })
        
        # 2. Validate individual parameters
        max_depth = optimizer.validate_numeric_param(
            query.get('max_depth'),
            'max_depth',
            min_value=1,
            max_value=10,
            default=2
        )
        
        max_results = optimizer.validate_numeric_param(
            query.get('max_results'),
            'max_results',
            min_value=1,
            max_value=100,
            default=10
        )
        
        # 3. Generate cache key
        cache_key = optimizer.generate_cache_key(
            query['vector'],
            max_depth=max_depth,
            max_results=max_results
        )
        
        # 4. Check cache
        if not optimizer.validate_cache_entry(cache_key):
            # Simulate query execution
            result = {"nodes": [1, 2, 3], "edges": []}
            
            # 5. Validate and sanitize result
            if optimizer.validate_result_for_caching(result):
                clean_result = optimizer.sanitize_for_cache(result)
                optimizer.query_cache[cache_key] = (clean_result, time.time())
        
        # Verify cache entry was created
        assert optimizer.validate_cache_entry(cache_key)
    
    def test_error_recovery_workflow(self):
        """Test error recovery in validation workflow."""
        optimizer = TestOptimizer()
        
        # Invalid query structure
        query = "invalid query"
        query = optimizer.ensure_query_defaults(query, {
            'max_depth': 2,
            'max_results': 10
        })
        
        # Should now be valid dict
        assert isinstance(query, dict)
        assert query['max_depth'] == 2
        
        # Invalid parameters
        max_depth = optimizer.validate_numeric_param(
            "invalid",
            'max_depth',
            min_value=1,
            max_value=10,
            default=2
        )
        
        # Should use default
        assert max_depth == 2
        
        # Out of range parameters
        max_results = optimizer.validate_numeric_param(
            1000,
            'max_results',
            min_value=1,
            max_value=100,
            default=10
        )
        
        # Should clamp to maximum
        assert max_results == 100
