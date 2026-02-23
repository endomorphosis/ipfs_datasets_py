"""Property-based tests for QueryValidationMixin using Hypothesis.

Tests invariants and properties that should hold for all possible inputs.
"""

import pytest
from hypothesis import given, strategies as st, assume, settings
from ipfs_datasets_py.optimizers.common.query_validation import QueryValidationMixin


class TestQueryValidationProperties:
    """Property-based tests for QueryValidationMixin."""
    
    def setup_method(self):
        """Set up test fixtures."""
        self.mixin = QueryValidationMixin()
    
    @given(
        value=st.one_of(
            st.integers(),
            st.floats(allow_nan=False, allow_infinity=False),
            st.none()
        ),
        min_value=st.integers(min_value=-1000, max_value=0),
        max_value=st.integers(min_value=1, max_value=1000),
    )
    @settings(max_examples=200)
    def test_numeric_param_always_within_bounds(self, value, min_value, max_value):
        """Validated numeric params are always within [min, max]."""
        assume(min_value < max_value)  # Ensure valid range
        
        result = self.mixin.validate_numeric_param(
            value=value,
            param_name="test_param",
            min_value=min_value,
            max_value=max_value,
            default=min_value,
        )
        
        # Property: Result must be within bounds
        assert min_value <= result <= max_value
        assert isinstance(result, (int, float))
    
    @given(
        value=st.floats(min_value=0.0, max_value=1.0, allow_nan=False),
    )
    @settings(max_examples=100)
    def test_numeric_param_preserves_valid_values(self, value):
        """Valid values within range are preserved unchanged."""
        result = self.mixin.validate_numeric_param(
            value=value,
            param_name="test_param",
            min_value=0.0,
            max_value=1.0,
            default=0.5,
        )
        
        # Property: Valid values should be preserved
        assert result == pytest.approx(value)
    
    @given(
        items=st.lists(st.text(min_size=1, max_size=20), min_size=0, max_size=50),
    )
    @settings(max_examples=100)
    def test_list_param_preserves_list_type(self, items):
        """List validation always returns list or None."""
        result = self.mixin.validate_list_param(
            value=items,
            param_name="test_list",
            default=None,
            allow_none=True,
        )
        
        # Property: Result is always a list or None
        assert result is None or isinstance(result, list)
        
        if result is not None:
            # Property: All items are preserved
            assert len(result) == len(items)
    
    @given(
        items=st.lists(st.integers(), min_size=0, max_size=30),
        min_length=st.integers(min_value=0, max_value=10),
        max_length=st.integers(min_value=11, max_value=50),
    )
    @settings(max_examples=100)
    def test_list_param_respects_length_constraints(self, items, min_length, max_length):
        """List length is always within constraints."""
        result = self.mixin.validate_list_param(
            value=items,
            param_name="test_list",
            min_length=min_length,
            max_length=max_length,
            default=[],
        )
        
        # Property: Result length is within bounds or uses default
        if result:
            assert min_length <= len(result) <= max_length
    
    @given(
        value=st.text(min_size=0, max_size=100),
        allowed_values=st.lists(st.text(min_size=1, max_size=10), min_size=1, max_size=5, unique=True),
    )
    @settings(max_examples=100)
    def test_string_param_enum_constraint(self, value, allowed_values):
        """String param is always one of allowed values or default."""
        default = allowed_values[0]
        
        result = self.mixin.validate_string_param(
            value=value,
            param_name="test_string",
            allowed_values=allowed_values,
            default=default,
        )
        
        # Property: Result is always in allowed_values
        assert result in allowed_values
    
    @given(
        query=st.dictionaries(
            keys=st.text(min_size=1, max_size=20),
            values=st.one_of(
                st.integers(),
                st.floats(allow_nan=False, allow_infinity=False),
                st.text(max_size=50),
                st.booleans(),
            ),
            min_size=0,
            max_size=20,
        ),
    )
    @settings(max_examples=100)
    def test_cache_key_generation_is_deterministic(self, query):
        """Same query always generates same cache key."""
        key1 = self.mixin.generate_cache_key(query)
        key2 = self.mixin.generate_cache_key(query)
        
        # Property: Deterministic key generation
        assert key1 == key2
        assert isinstance(key1, str)
        assert len(key1) > 0
    
    @given(
        query1=st.dictionaries(
            keys=st.text(min_size=1, max_size=10),
            values=st.integers(),
            min_size=1,
            max_size=5,
        ),
        query2=st.dictionaries(
            keys=st.text(min_size=1, max_size=10),
            values=st.integers(),
            min_size=1,
            max_size=5,
        ),
    )
    @settings(max_examples=100)
    def test_cache_key_different_for_different_queries(self, query1, query2):
        """Different queries generate different cache keys."""
        assume(query1 != query2)  # Only test when queries differ
        
        key1 = self.mixin.generate_cache_key(query1)
        key2 = self.mixin.generate_cache_key(query2)
        
        # Property: Different inputs produce different keys
        assert key1 != key2
    
    @given(
        min_value=st.floats(min_value=-1000, max_value=0, allow_nan=False, allow_infinity=False),
        max_value=st.floats(min_value=1, max_value=1000, allow_nan=False, allow_infinity=False),
    )
    @settings(max_examples=100)
    def test_numeric_param_default_within_bounds(self, min_value, max_value):
        """Default value is used when value is None."""
        assume(min_value < max_value)
        
        default = (min_value + max_value) / 2.0
        
        result = self.mixin.validate_numeric_param(
            value=None,
            param_name="test_param",
            min_value=min_value,
            max_value=max_value,
            default=default,
        )
        
        # Property: When value is None, default is returned
        assert result == pytest.approx(default)
    
    @given(
        value=st.integers(),
    )
    @settings(max_examples=100)
    def test_numeric_param_bounds_clamping(self, value):
        """Values outside bounds are clamped to bounds."""
        min_val = 0
        max_val = 100
        
        result = self.mixin.validate_numeric_param(
            value=value,
            param_name="test_param",
            min_value=min_val,
            max_value=max_val,
            default=50,
        )
        
        # Property: Clamping to bounds
        if value < min_val:
            assert result == min_val
        elif value > max_val:
            assert result == max_val
        else:
            assert result == value


class TestQueryStructureValidationProperties:
    """Property-based tests for query structure validation."""
    
    def setup_method(self):
        """Set up test fixtures."""
        self.mixin = QueryValidationMixin()
    
    @given(
        query=st.dictionaries(
            keys=st.text(min_size=1, max_size=20, alphabet=st.characters(min_codepoint=97, max_codepoint=122)),
            values=st.one_of(
                st.integers(min_value=-1000, max_value=1000),
                st.floats(min_value=-100, max_value=100, allow_nan=False, allow_infinity=False),
                st.text(max_size=50),
                st.booleans(),
                st.none(),
            ),
            min_size=1,
            max_size=10,
        ),
    )
    @settings(max_examples=100)
    def test_validate_query_structure_returns_bool(self, query):
        """Query validation returns boolean for dict inputs."""
        result = self.mixin.validate_query_structure(query)
        
        # Property: Returns boolean
        assert isinstance(result, bool)
        # Dictionary inputs should be valid
        assert result is True
    
    @given(
        items=st.lists(st.integers(), min_size=0, max_size=20),
    )
    @settings(max_examples=50)
    def test_list_param_idempotent(self, items):
        """Validating twice gives same result as validating once."""
        result1 = self.mixin.validate_list_param(
            value=items,
            param_name="test_list",
            default=[],
        )
        
        result2 = self.mixin.validate_list_param(
            value=result1,
            param_name="test_list",
            default=[],
        )
        
        # Property: Idempotence
        assert result1 == result2
    
    @given(
        value=st.floats(allow_nan=False, allow_infinity=False),
        min_value=st.floats(min_value=-100, max_value=0, allow_nan=False, allow_infinity=False),
        max_value=st.floats(min_value=1, max_value=100, allow_nan=False, allow_infinity=False),
    )
    @settings(max_examples=100)
    def test_numeric_param_idempotent(self, value, min_value, max_value):
        """Validating twice gives same result as validating once."""
        assume(min_value < max_value)
        
        result1 = self.mixin.validate_numeric_param(
            value=value,
            param_name="test_param",
            min_value=min_value,
            max_value=max_value,
            default=0.0,
        )
        
        result2 = self.mixin.validate_numeric_param(
            value=result1,
            param_name="test_param",
            min_value=min_value,
            max_value=max_value,
            default=0.0,
        )
        
        # Property: Idempotence
        assert result1 == pytest.approx(result2)


class TestCacheValidationProperties:
    """Property-based tests for cache validation."""
    
    def setup_method(self):
        """Set up test fixtures."""
        self.mixin = QueryValidationMixin()
    
    @given(
        query=st.dictionaries(
            keys=st.text(min_size=1, max_size=10),
            values=st.one_of(
                st.integers(),
                st.floats(allow_nan=False, allow_infinity=False),
                st.text(max_size=20),
            ),
            min_size=0,
            max_size=10,
        ),
        check_expiration=st.booleans(),
    )
    @settings(max_examples=50)
    def test_cache_entry_validation_returns_bool(self, query, check_expiration):
        """Cache entry validation returns boolean."""
        cache_key = self.mixin.generate_cache_key(query)
        is_valid = self.mixin.validate_cache_entry(cache_key, check_expiration=check_expiration)
        
        # Property: Boolean result
        assert isinstance(is_valid, bool)
    
    @given(
        query=st.dictionaries(
            keys=st.text(min_size=1, max_size=15),
            values=st.integers(min_value=0, max_value=1000),
            min_size=1,
            max_size=8,
        ),
    )
    @settings(max_examples=100)
    def test_cache_key_length_bounded(self, query):
        """Cache keys have bounded length."""
        key = self.mixin.generate_cache_key(query)
        
        # Property: Key length is reasonable (hash-based)
        assert 10 <= len(key) <= 100  # Typical hash length range


class TestEdgeCaseProperties:
    """Property-based tests for edge cases."""
    
    def setup_method(self):
        """Set up test fixtures."""
        self.mixin = QueryValidationMixin()
    
    @given(
        value=st.one_of(st.text(max_size=50), st.integers(), st.floats(allow_nan=False), st.none()),
    )
    @settings(max_examples=100)
    def test_numeric_param_handles_type_conversion(self, value):
        """Numeric param attempts type conversion for all inputs."""
        result = self.mixin.validate_numeric_param(
            value=value,
            param_name="test_param",
            min_value=0,
            max_value=100,
            default=50,
        )
        
        # Property: Always returns a number (or uses default)
        assert isinstance(result, (int, float))
        assert 0 <= result <= 100
    
    @given(
        items=st.one_of(
            st.lists(st.integers(), max_size=20),
            st.text(max_size=20),
            st.integers(),
            st.none(),
        ),
    )
    @settings(max_examples=100)
    def test_list_param_handles_invalid_types(self, items):
        """List param handles non-list inputs gracefully."""
        result = self.mixin.validate_list_param(
            value=items,
            param_name="test_list",
            default=[],
            allow_none=True,
        )
        
        # Property: Always returns list or None
        assert result is None or isinstance(result, list)
    
    @given(
        value=st.text(min_size=0, max_size=100),
    )
    @settings(max_examples=50)
    def test_string_param_with_no_constraints(self, value):
        """String param without constraints accepts any string."""
        result = self.mixin.validate_string_param(
            value=value,
            param_name="test_string",
            allowed_values=None,  # No constraints
            default="",
        )
        
        # Property: Returns input or default
        assert isinstance(result, str)
        assert result == value or result == ""


class TestCompositeValidationProperties:
    """Property-based tests for composite validation scenarios."""
    
    def setup_method(self):
        """Set up test fixtures."""
        self.mixin = QueryValidationMixin()
    
    @given(
        max_results=st.integers(min_value=-100, max_value=2000),
        min_similarity=st.floats(min_value=-1.0, max_value=2.0, allow_nan=False, allow_infinity=False),
        max_depth=st.integers(min_value=-10, max_value=50),
    )
    @settings(max_examples=100)
    def test_multiple_param_validation_independence(self, max_results, min_similarity, max_depth):
        """Validating multiple params independently maintains constraints."""
        # Validate each param
        validated_results = self.mixin.validate_numeric_param(
            value=max_results,
            param_name="max_results",
            min_value=1,
            max_value=1000,
            default=10,
        )
        
        validated_similarity = self.mixin.validate_numeric_param(
            value=min_similarity,
            param_name="min_similarity",
            min_value=0.0,
            max_value=1.0,
            default=0.5,
        )
        
        validated_depth = self.mixin.validate_numeric_param(
            value=max_depth,
            param_name="max_depth",
            min_value=1,
            max_value=10,
            default=2,
        )
        
        # Property: Each validation is independent and maintains its constraint
        assert 1 <= validated_results <= 1000
        assert 0.0 <= validated_similarity <= 1.0
        assert 1 <= validated_depth <= 10
