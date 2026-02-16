"""
Tests for Cypher list functions.

Tests the list manipulation functions:
- range(start, end, step)
- head(list)
- tail(list)
- last(list)
- reverse(list)
- size(collection)
"""

import pytest
from ipfs_datasets_py.knowledge_graphs.cypher.functions import (
    fn_range,
    fn_head,
    fn_tail,
    fn_last,
    fn_reverse,
    fn_size,
    evaluate_function
)


class TestRangeFunction:
    """Tests for range() function."""
    
    def test_range_basic(self):
        """Test basic range generation."""
        result = fn_range(0, 5)
        assert result == [0, 1, 2, 3, 4]
    
    def test_range_with_step(self):
        """Test range with custom step."""
        result = fn_range(0, 10, 2)
        assert result == [0, 2, 4, 6, 8]
    
    def test_range_negative_step(self):
        """Test range with negative step."""
        result = fn_range(5, 0, -1)
        assert result == [5, 4, 3, 2, 1]
    
    def test_range_empty(self):
        """Test range that produces empty list."""
        result = fn_range(0, 0)
        assert result == []
    
    def test_range_single_element(self):
        """Test range with single element."""
        result = fn_range(5, 6)
        assert result == [5]
    
    def test_range_null_start(self):
        """Test range with NULL start."""
        result = fn_range(None, 5)
        assert result is None
    
    def test_range_null_end(self):
        """Test range with NULL end."""
        result = fn_range(0, None)
        assert result is None
    
    def test_range_via_registry(self):
        """Test range via function registry."""
        result = evaluate_function('range', 0, 3)
        assert result == [0, 1, 2]


class TestHeadFunction:
    """Tests for head() function."""
    
    def test_head_basic(self):
        """Test getting first element."""
        result = fn_head([1, 2, 3])
        assert result == 1
    
    def test_head_single_element(self):
        """Test head on single-element list."""
        result = fn_head([42])
        assert result == 42
    
    def test_head_empty_list(self):
        """Test head on empty list."""
        result = fn_head([])
        assert result is None
    
    def test_head_null(self):
        """Test head on NULL."""
        result = fn_head(None)
        assert result is None
    
    def test_head_strings(self):
        """Test head on list of strings."""
        result = fn_head(['a', 'b', 'c'])
        assert result == 'a'
    
    def test_head_via_registry(self):
        """Test head via function registry."""
        result = evaluate_function('head', [10, 20, 30])
        assert result == 10


class TestTailFunction:
    """Tests for tail() function."""
    
    def test_tail_basic(self):
        """Test getting all but first element."""
        result = fn_tail([1, 2, 3, 4])
        assert result == [2, 3, 4]
    
    def test_tail_two_elements(self):
        """Test tail on two-element list."""
        result = fn_tail([1, 2])
        assert result == [2]
    
    def test_tail_single_element(self):
        """Test tail on single-element list."""
        result = fn_tail([42])
        assert result == []
    
    def test_tail_empty_list(self):
        """Test tail on empty list."""
        result = fn_tail([])
        assert result == []
    
    def test_tail_null(self):
        """Test tail on NULL."""
        result = fn_tail(None)
        assert result is None
    
    def test_tail_via_registry(self):
        """Test tail via function registry."""
        result = evaluate_function('tail', ['a', 'b', 'c'])
        assert result == ['b', 'c']


class TestLastFunction:
    """Tests for last() function."""
    
    def test_last_basic(self):
        """Test getting last element."""
        result = fn_last([1, 2, 3])
        assert result == 3
    
    def test_last_single_element(self):
        """Test last on single-element list."""
        result = fn_last([42])
        assert result == 42
    
    def test_last_empty_list(self):
        """Test last on empty list."""
        result = fn_last([])
        assert result is None
    
    def test_last_null(self):
        """Test last on NULL."""
        result = fn_last(None)
        assert result is None
    
    def test_last_strings(self):
        """Test last on list of strings."""
        result = fn_last(['x', 'y', 'z'])
        assert result == 'z'
    
    def test_last_via_registry(self):
        """Test last via function registry."""
        result = evaluate_function('last', [100, 200, 300])
        assert result == 300


class TestReverseFunction:
    """Tests for reverse() function."""
    
    def test_reverse_basic(self):
        """Test reversing a list."""
        result = fn_reverse([1, 2, 3])
        assert result == [3, 2, 1]
    
    def test_reverse_single_element(self):
        """Test reverse on single-element list."""
        result = fn_reverse([42])
        assert result == [42]
    
    def test_reverse_empty_list(self):
        """Test reverse on empty list."""
        result = fn_reverse([])
        assert result == []
    
    def test_reverse_null(self):
        """Test reverse on NULL."""
        result = fn_reverse(None)
        assert result is None
    
    def test_reverse_strings(self):
        """Test reverse on list of strings."""
        result = fn_reverse(['a', 'b', 'c'])
        assert result == ['c', 'b', 'a']
    
    def test_reverse_string(self):
        """Test reverse on string."""
        result = fn_reverse("hello")
        assert result == "olleh"
    
    def test_reverse_via_registry(self):
        """Test reverse via function registry."""
        result = evaluate_function('reverse', [5, 4, 3, 2, 1])
        assert result == [1, 2, 3, 4, 5]


class TestSizeFunction:
    """Tests for size() function."""
    
    def test_size_list(self):
        """Test size on list."""
        result = fn_size([1, 2, 3])
        assert result == 3
    
    def test_size_string(self):
        """Test size on string."""
        result = fn_size("hello")
        assert result == 5
    
    def test_size_dict(self):
        """Test size on dictionary."""
        result = fn_size({'a': 1, 'b': 2})
        assert result == 2
    
    def test_size_empty_list(self):
        """Test size on empty list."""
        result = fn_size([])
        assert result == 0
    
    def test_size_empty_string(self):
        """Test size on empty string."""
        result = fn_size("")
        assert result == 0
    
    def test_size_null(self):
        """Test size on NULL."""
        result = fn_size(None)
        assert result is None
    
    def test_size_via_registry(self):
        """Test size via function registry."""
        result = evaluate_function('size', [10, 20, 30, 40])
        assert result == 4


class TestListFunctionsIntegration:
    """Integration tests combining multiple list functions."""
    
    def test_range_and_reverse(self):
        """Test chaining range and reverse."""
        numbers = fn_range(1, 6)
        reversed_numbers = fn_reverse(numbers)
        assert reversed_numbers == [5, 4, 3, 2, 1]
    
    def test_range_head_last(self):
        """Test range with head and last."""
        numbers = fn_range(10, 20, 2)
        assert fn_head(numbers) == 10
        assert fn_last(numbers) == 18
    
    def test_tail_and_size(self):
        """Test tail and size."""
        original = [1, 2, 3, 4, 5]
        tail_list = fn_tail(original)
        assert fn_size(tail_list) == 4
    
    def test_empty_list_operations(self):
        """Test multiple operations on empty list."""
        empty = []
        assert fn_head(empty) is None
        assert fn_last(empty) is None
        assert fn_tail(empty) == []
        assert fn_reverse(empty) == []
        assert fn_size(empty) == 0


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
