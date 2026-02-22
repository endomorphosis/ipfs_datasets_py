"""Integration tests for QueryValidationMixin with real optimizer classes.

This module tests that QueryValidationMixin integrates correctly with actual
GraphRAG and Logic query optimizers, verifying the mixin methods work in
real-world usage scenarios.
"""

import pytest
from unittest.mock import MagicMock, patch
import numpy as np
from ipfs_datasets_py.optimizers.common.query_validation import QueryValidationMixin


class MockQueryOptimizerWithValidation(QueryValidationMixin):
    """Mock query optimizer that uses QueryValidationMixin."""
    
    def __init__(self):
        self._log = MagicMock()
        self._cache_enabled = True
        self._cache = {}
    
    def optimize_query(self, query: dict) -> dict:
        """Example optimization that uses validation methods."""
        # Validate and normalize numeric parameters
        depth = self.validate_numeric_param(
            query.get('depth'),
            param_name='depth',
            min_value=1,
            max_value=5,
            default=2
        )
        
        # Validate list parameters
        filters = self.validate_list_param(
            query.get('filters'),
            param_name='filters',
            element_type=str,
            default=[]
        )
        
        # Validate string parameters
        strategy = self.validate_string_param(
            query.get('strategy'),
            param_name='strategy',
            allowed_values=['bfs', 'dfs', 'adaptive'],
            default='bfs',
            case_sensitive=True
        )
        
        # Build validated query with safe values
        validated_query = {
            'depth': depth,
            'filters': filters,
            'strategy': strategy,
            'max_results': query.get('max_results', 100)
        }
        
        return validated_query
    
    def cached_operation(self, query: dict) -> dict:
        """Example cached operation using validation methods."""
        cache_key = self.generate_cache_key(query)
        
        if cache_key in self._cache:
            entry = self._cache[cache_key]
            if self.validate_cache_entry(entry):
                return entry['result']
        
        # Perform operation
        result = {'processed': True, 'query': query}
        
        # Cache the result
        self._cache[cache_key] = {
            'result': result,
            'timestamp': 12345,
            'valid': True
        }
        
        return result


class TestQueryValidationMixinIntegration:
    """Test QueryValidationMixin integration with mock optimizers."""
    
    def test_optimize_query_with_validation(self):
        """Test that optimize_query uses validation correctly."""
        optimizer = MockQueryOptimizerWithValidation()
        
        query = {
            'depth': 3,
            'filters': ['type:person', 'confidence>0.5'],
            'strategy': 'dfs'
        }
        
        result = optimizer.optimize_query(query)
        
        assert result['depth'] == 3
        assert result['filters'] == ['type:person', 'confidence>0.5']
        assert result['strategy'] == 'dfs'
        assert result['max_results'] == 100  # Default applied
    
    def test_optimize_query_applies_defaults(self):
        """Test that missing parameters get defaults."""
        optimizer = MockQueryOptimizerWithValidation()
        
        query = {}  # Empty query
        
        result = optimizer.optimize_query(query)
        
        assert result['depth'] == 2  # Default
        assert result['filters'] == []  # Default
        assert result['strategy'] == 'bfs'  # Default
        assert result['max_results'] == 100  # Default
    
    def test_optimize_query_validates_numeric_ranges(self):
        """Test that numeric parameters are clamped to valid ranges."""
        optimizer = MockQueryOptimizerWithValidation()
        
        query = {'depth': 10}  # Above max (5)
        
        result = optimizer.optimize_query(query)
        
        assert result['depth'] == 5  # Clamped to max
    
    def test_optimize_query_filters_invalid_list_elements(self):
        """Test that list elements are converted to specified type."""
        optimizer = MockQueryOptimizerWithValidation()
        
        query = {
            'filters': ['valid_filter', 123, None, 'another_filter']
        }
        
        result = optimizer.optimize_query(query)
        
        # element_type=str converts elements to strings
        assert result['filters'] == ['valid_filter', '123', 'None', 'another_filter']
    
    def test_optimize_query_validates_string_enum(self):
        """Test that invalid string values fall back to default."""
        optimizer = MockQueryOptimizerWithValidation()
        
        query = {'strategy': 'invalid_strategy'}
        
        result = optimizer.optimize_query(query)
        
        assert result['strategy'] == 'bfs'  # Fallen back to default
    
    def test_cached_operation_generates_consistent_keys(self):
        """Test that cache keys are consistent for same query."""
        optimizer = MockQueryOptimizerWithValidation()
        
        query = {'depth': 2, 'strategy': 'bfs'}
        
        key1 = optimizer.generate_cache_key(query)
        key2 = optimizer.generate_cache_key(query)
        
        assert key1 == key2
    
    def test_cached_operation_uses_cache(self):
        """Test that cached results are returned."""
        optimizer = MockQueryOptimizerWithValidation()
        
        query = {'depth': 2}
        
        # First call - miss
        result1 = optimizer.cached_operation(query)
        
        # Second call - hit
        result2 = optimizer.cached_operation(query)
        
        assert result1 == result2
        assert len(optimizer._cache) == 1
    
    def test_cached_operation_validates_entries(self):
        """Test that invalid cache entries are rejected."""
        optimizer = MockQueryOptimizerWithValidation()
        
        query = {'depth': 2}
        cache_key = optimizer.generate_cache_key(query)
        
        # Add invalid cache entry (missing required fields)
        optimizer._cache[cache_key] = {
            'result': {'bad': 'entry'}
            # Missing timestamp and valid fields
        }
        
        # Should not use the invalid entry
        result = optimizer.cached_operation(query)
        
        # Cache should be updated with valid entry
        assert optimizer._cache[cache_key]['timestamp'] is not None
        assert optimizer._cache[cache_key]['valid'] is True


class TestQueryValidationWithNumpy:
    """Test QueryValidationMixin with numpy array handling."""
    
    def test_cache_key_with_numpy_arrays(self):
        """Test that numpy arrays are handled in cache key generation."""
        optimizer = MockQueryOptimizerWithValidation()
        
        query = {
            'vector': np.array([1.0, 2.0, 3.0]),
            'depth': 2
        }
        
        # Should not raise
        cache_key = optimizer.generate_cache_key(query)
        
        assert isinstance(cache_key, str)
        assert len(cache_key) > 0
    
    def test_sanitize_for_cache_numpy_arrays(self):
        """Test that numpy arrays are converted for caching."""
        optimizer = MockQueryOptimizerWithValidation()
        
        value = np.array([1, 2, 3])
        
        sanitized = optimizer.sanitize_for_cache(value)
        
        assert isinstance(sanitized, list)
        assert sanitized == [1, 2, 3]
    
    def test_sanitize_for_cache_nested_numpy(self):
        """Test that nested numpy arrays are converted."""
        optimizer = MockQueryOptimizerWithValidation()
        
        value = {
            'vectors': [
                np.array([1.0, 2.0]),
                np.array([3.0, 4.0])
            ],
            'scores': np.array([0.5, 0.8])
        }
        
        sanitized = optimizer.sanitize_for_cache(value)
        
        assert isinstance(sanitized['vectors'], list)
        assert all(isinstance(v, list) for v in sanitized['vectors'])
        assert isinstance(sanitized['scores'], list)


class TestQueryValidationNested:
    """Test nested query structure validation."""
    
    def test_ensure_nested_dict(self):
        """Test creation of nested dictionary structures."""
        optimizer = MockQueryOptimizerWithValidation()
        
        query = {}
        
        result = optimizer.ensure_nested_dict(
            query,
            'config', 'optimization', 'strategy',
            default_value='bfs'
        )
        
        # The method mutates the input dict
        assert query == {
            'config': {
                'optimization': {
                    'strategy': 'bfs'
                }
            }
        }
    
    def test_ensure_nested_dict_preserves_existing(self):
        """Test that existing nested values are preserved."""
        optimizer = MockQueryOptimizerWithValidation()
        
        query = {
            'config': {
                'other': 'value'
            }
        }
        
        optimizer.ensure_nested_dict(
            query,
            'config', 'optimization', 'depth',
            default_value=2
        )
        
        assert query['config']['other'] == 'value'
        assert query['config']['optimization']['depth'] == 2
    
    def test_ensure_nested_dict_doesnt_override(self):
        """Test that existing values are not overridden."""
        optimizer = MockQueryOptimizerWithValidation()
        
        query = {
            'config': {
                'optimization': {
                    'depth': 5
                }
            }
        }
        
        optimizer.ensure_nested_dict(
            query,
            'config', 'optimization', 'depth',
            default_value=2
        )
        
        assert query['config']['optimization']['depth'] == 5  # Not overridden


class TestQueryValidationErrorHandling:
    """Test error handling in QueryValidationMixin."""
    
    def test_validate_numeric_param_handles_none(self):
        """Test that None values are handled gracefully."""
        optimizer = MockQueryOptimizerWithValidation()
        
        result = optimizer.validate_numeric_param(
            None,
            param_name='test',
            default=5
        )
        
        assert result == 5
    
    def test_validate_list_param_converts_tuple(self):
        """Test that tuples are converted to lists."""
        optimizer = MockQueryOptimizerWithValidation()
        
        result = optimizer.validate_list_param(
            (1, 2, 3),
            param_name='test'
        )
        
        assert isinstance(result, list)
        assert result == [1, 2, 3]
    
    def test_validate_string_param_converts_numbers(self):
        """Test that numbers are converted to strings."""
        optimizer = MockQueryOptimizerWithValidation()
        
        result = optimizer.validate_string_param(
            123,
            param_name='test'
        )
        
        assert isinstance(result, str)
        assert result == '123'
    
    def test_cache_key_generation_handles_unhashable(self):
        """Test that unhashable types don't crash key generation."""
        optimizer = MockQueryOptimizerWithValidation()
        
        query = {
            'list': [1, 2, 3],
            'dict': {'nested': 'value'},
            'normal': 'string'
        }
        
        # Should not raise
        cache_key = optimizer.generate_cache_key(query)
        
        assert isinstance(cache_key, str)


class TestQueryValidationRealWorldScenarios:
    """Test realistic query validation scenarios."""
    
    def test_graph_traversal_query_validation(self):
        """Test validation of typical graph traversal query."""
        optimizer = MockQueryOptimizerWithValidation()
        
        query = {
            'depth': '3',  # String (should convert)
            'filters': ('type:person',),  # Tuple (should convert)
            'strategy': 'adaptive',
            'max_results': 50
        }
        
        result = optimizer.optimize_query(query)
        
        assert result['depth'] == 3  # Converted to int
        assert isinstance(result['filters'], list)
        assert result['strategy'] == 'adaptive'
    
    def test_malformed_query_recovery(self):
        """Test that malformed queries are recovered."""
        optimizer = MockQueryOptimizerWithValidation()
        
        query = {
            'depth': 'invalid',  # Invalid number
            'filters': 'not_a_list',  # Invalid list
            'strategy': 'invalid_strat'  # Invalid enum
        }
        
        result = optimizer.optimize_query(query)
        
        # All values should fall back to defaults
        assert result['depth'] == 2
        assert result['filters'] == []
        assert result['strategy'] == 'bfs'
    
    def test_query_with_complex_nesting(self):
        """Test validation with deeply nested query structures."""
        optimizer = MockQueryOptimizerWithValidation()
        
        query = {
            'depth': 3,
            'config': {
                'optimization': {
                    'enabled': True,
                    'strategy': 'adaptive'
                }
            }
        }
        
        # Ensure additional nested defaults
        optimizer.ensure_nested_dict(
            query,
            ['config', 'caching', 'ttl'],
            default_value=3600
        )
        
        assert query['config']['optimization']['enabled'] is True
        assert query['config']['caching']['ttl'] == 3600
