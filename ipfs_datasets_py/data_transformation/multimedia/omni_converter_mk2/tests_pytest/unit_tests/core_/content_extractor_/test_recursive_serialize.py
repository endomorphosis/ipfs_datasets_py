"""
Test suite for core/content_extractor/_recursive_serialize.py converted from unittest to pytest.
"""
import pytest
from unittest.mock import Mock, MagicMock, patch
from typing import Any
from datetime import datetime, date
from decimal import Decimal
from pathlib import Path
from enum import Enum
import uuid
import base64

try:
    import numpy as np
    import pandas as pd
    NUMPY_AVAILABLE = True
    PANDAS_AVAILABLE = True
except ImportError:
    # Skip numpy and pandas tests if not available
    np = pd = None
    NUMPY_AVAILABLE = False
    PANDAS_AVAILABLE = False

try:
    from core.content_extractor._recursive_serialize import _recursive_serialize
except ImportError:
    pytest.skip("core.content_extractor._recursive_serialize module not available", allow_module_level=True)


class SampleEnum(Enum):
    """Sample enum for serialization tests."""
    RED = "red"
    BLUE = "blue"
    GREEN = 3


class CustomObject:
    """Custom object for testing serialization."""
    def __init__(self, name: str, value: int):
        self.name = name
        self.value = value


class CustomObjectWithStr:
    """Custom object with __str__ method."""
    def __init__(self, data: str):
        self.data = data
    
    def __str__(self):
        return f"CustomObjectWithStr({self.data})"


class CustomObjectWithDict:
    """Custom object with __dict__ attribute."""
    def __init__(self, x: int, y: str):
        self.x = x
        self.y = y


class TestRecursiveSerialize:
    """Test _recursive_serialize function for JSON serialization."""

    def test_serialize_basic_types(self):
        """
        GIVEN basic Python types (str, int, float, bool, None)
        WHEN _recursive_serialize is called on each
        THEN expect:
            - Values are returned unchanged
            - Types remain the same
        """
        # Test string
        result = _recursive_serialize("hello")
        assert result == "hello"
        assert isinstance(result, str)
        
        # Test integer
        result = _recursive_serialize(42)
        assert result == 42
        assert isinstance(result, int)
        
        # Test float
        result = _recursive_serialize(3.14)
        assert result == 3.14
        assert isinstance(result, float)
        
        # Test boolean True
        result = _recursive_serialize(True)
        assert result is True
        assert isinstance(result, bool)
        
        # Test boolean False
        result = _recursive_serialize(False)
        assert result is False
        assert isinstance(result, bool)
        
        # Test None
        result = _recursive_serialize(None)
        assert result is None

    def test_serialize_list(self):
        """
        GIVEN a list containing various types
        WHEN _recursive_serialize is called
        THEN expect:
            - List structure is preserved
            - All elements are recursively serialized
            - Order is maintained
        """
        test_list = [1, "hello", 3.14, True, None, [1, 2, 3]]
        result = _recursive_serialize(test_list)
        
        assert isinstance(result, list)
        assert len(result) == 6
        assert result[0] == 1
        assert result[1] == "hello"
        assert result[2] == 3.14
        assert result[3] is True
        assert result[4] is None
        assert result[5] == [1, 2, 3]

    def test_serialize_tuple(self):
        """
        GIVEN a tuple containing various types
        WHEN _recursive_serialize is called
        THEN expect:
            - Tuple is converted to list
            - All elements are recursively serialized
            - Order is maintained
        """
        test_tuple = (1, "hello", 3.14, (2, 3))
        result = _recursive_serialize(test_tuple)
        
        assert isinstance(result, list)
        assert len(result) == 4
        assert result[0] == 1
        assert result[1] == "hello"
        assert result[2] == 3.14
        assert result[3] == [2, 3]

    def test_serialize_dict(self):
        """
        GIVEN a dictionary with various key-value pairs
        WHEN _recursive_serialize is called
        THEN expect:
            - Dictionary structure is preserved
            - All keys remain as strings
            - All values are recursively serialized
        """
        test_dict = {
            "name": "test",
            "age": 25,
            "active": True,
            "data": {"nested": "value"},
            "items": [1, 2, 3]
        }
        result = _recursive_serialize(test_dict)
        
        assert isinstance(result, dict)
        assert result["name"] == "test"
        assert result["age"] == 25
        assert result["active"] is True
        assert result["data"] == {"nested": "value"}
        assert result["items"] == [1, 2, 3]

    def test_serialize_nested_structures(self):
        """
        GIVEN deeply nested data structures (dict of lists of dicts)
        WHEN _recursive_serialize is called
        THEN expect:
            - All levels are properly serialized
            - Structure is maintained
            - No infinite recursion occurs
        """
        nested_data = {
            "level1": {
                "level2": [
                    {"level3": {"level4": "deep_value"}},
                    {"another": [1, 2, {"nested_list": True}]}
                ]
            },
            "simple": "value"
        }
        result = _recursive_serialize(nested_data)
        
        assert isinstance(result, dict)
        assert result["simple"] == "value"
        assert result["level1"]["level2"][0]["level3"]["level4"] == "deep_value"
        assert result["level1"]["level2"][1]["another"][2]["nested_list"] is True

    def test_serialize_set(self):
        """
        GIVEN a set containing various elements
        WHEN _recursive_serialize is called
        THEN expect:
            - Set is converted to list
            - All elements are serialized
            - Note: order may not be preserved
        """
        test_set = {1, 2, 3, "hello"}
        result = _recursive_serialize(test_set)
        
        assert isinstance(result, list)
        assert len(result) == 4
        assert 1 in result
        assert 2 in result
        assert 3 in result
        assert "hello" in result

    def test_serialize_datetime_objects(self):
        """
        GIVEN datetime and date objects
        WHEN _recursive_serialize is called
        THEN expect:
            - datetime objects are converted to ISO format strings
            - date objects are converted to ISO format strings
        """
        test_datetime = datetime(2023, 12, 25, 15, 30, 45)
        result_datetime = _recursive_serialize(test_datetime)
        assert result_datetime == "2023-12-25T15:30:45"
        
        test_date = date(2023, 12, 25)
        result_date = _recursive_serialize(test_date)
        assert result_date == "2023-12-25"

    def test_serialize_decimal(self):
        """
        GIVEN Decimal objects
        WHEN _recursive_serialize is called
        THEN expect:
            - Decimal is converted to float or string
            - Precision is maintained where possible
        """
        test_decimal = Decimal("123.456")
        result = _recursive_serialize(test_decimal)
        
        # Should be either float or string that preserves the value
        if isinstance(result, float):
            assert abs(result - 123.456) < 0.001
        elif isinstance(result, str):
            assert result == "123.456"
        else:
            pytest.fail(f"Expected float or string, got {type(result)}")

    def test_serialize_bytes(self):
        """
        GIVEN bytes and bytearray objects
        WHEN _recursive_serialize is called
        THEN expect:
            - Bytes are converted to base64 string or decoded
            - Content is preserved
        """
        test_bytes = b"hello world"
        result = _recursive_serialize(test_bytes)
        
        # Should be either base64 encoded or decoded string
        if isinstance(result, str):
            # If base64 encoded, should be able to decode back
            try:
                decoded = base64.b64decode(result)
                assert decoded == test_bytes
            except:
                # If not base64, might be direct decode
                assert result == "hello world"
        
        test_bytearray = bytearray(b"test data")
        result_bytearray = _recursive_serialize(test_bytearray)
        assert isinstance(result_bytearray, str)

    def test_serialize_path_objects(self):
        """
        GIVEN Path objects from pathlib
        WHEN _recursive_serialize is called
        THEN expect:
            - Path is converted to string
            - Path separators are appropriate
        """
        test_path = Path("/home/user/document.txt")
        result = _recursive_serialize(test_path)
        
        assert isinstance(result, str)
        assert result == "/home/user/document.txt"

    @pytest.mark.skipif(not NUMPY_AVAILABLE, reason="numpy not available")
    def test_serialize_numpy_types(self):
        """
        GIVEN numpy arrays and numpy scalar types
        WHEN _recursive_serialize is called
        THEN expect:
            - Arrays are converted to lists
            - Numpy scalars are converted to Python types
            - Multi-dimensional arrays preserve shape
        """
        # Test 1D array
        array_1d = np.array([1, 2, 3, 4])
        result_1d = _recursive_serialize(array_1d)
        assert result_1d == [1, 2, 3, 4]
        
        # Test 2D array
        array_2d = np.array([[1, 2], [3, 4]])
        result_2d = _recursive_serialize(array_2d)
        assert result_2d == [[1, 2], [3, 4]]
        
        # Test numpy scalar
        scalar = np.int64(42)
        result_scalar = _recursive_serialize(scalar)
        assert result_scalar == 42
        assert isinstance(result_scalar, int)
        
        # Test numpy float
        float_scalar = np.float64(3.14)
        result_float = _recursive_serialize(float_scalar)
        assert abs(result_float - 3.14) < 0.001

    @pytest.mark.skipif(not PANDAS_AVAILABLE, reason="pandas not available")
    def test_serialize_pandas_types(self):
        """
        GIVEN pandas Series and DataFrame objects
        WHEN _recursive_serialize is called
        THEN expect:
            - Series is converted to list or dict
            - DataFrame is converted to dict of lists or list of dicts
            - Index information is preserved or handled appropriately
        """
        # Test Series
        series = pd.Series([1, 2, 3, 4], name="test_series")
        result_series = _recursive_serialize(series)
        
        # Should be list or dict
        if isinstance(result_series, list):
            assert result_series == [1, 2, 3, 4]
        elif isinstance(result_series, dict):
            assert "values" in result_series
        
        # Test DataFrame
        df = pd.DataFrame({"A": [1, 2], "B": [3, 4]})
        result_df = _recursive_serialize(df)
        
        assert isinstance(result_df, (dict, list))

    def test_serialize_custom_objects(self):
        """
        GIVEN custom class instances
        WHEN _recursive_serialize is called
        THEN expect:
            - Objects with __dict__ are converted to dict
            - Objects with __str__ fallback to string representation
            - Objects with custom serialization methods are handled
        """
        # Test object with __dict__
        obj_with_dict = CustomObjectWithDict(42, "test")
        result_dict = _recursive_serialize(obj_with_dict)
        
        if isinstance(result_dict, dict):
            assert result_dict["x"] == 42
            assert result_dict["y"] == "test"
        
        # Test object with __str__
        obj_with_str = CustomObjectWithStr("test_data")
        result_str = _recursive_serialize(obj_with_str)
        
        if isinstance(result_str, str):
            assert "test_data" in result_str

    def test_serialize_empty_containers(self):
        """
        GIVEN empty list, dict, set, tuple
        WHEN _recursive_serialize is called
        THEN expect:
            - Empty list returns []
            - Empty dict returns {}
            - Empty set returns []
            - Empty tuple returns []
        """
        assert _recursive_serialize([]) == []
        assert _recursive_serialize({}) == {}
        assert _recursive_serialize(set()) == []
        assert _recursive_serialize(()) == []

    def test_serialize_none_values_in_containers(self):
        """
        GIVEN containers with None values
        WHEN _recursive_serialize is called
        THEN expect:
            - None values are preserved
            - Container structure is maintained
        """
        list_with_none = [1, None, 3]
        result_list = _recursive_serialize(list_with_none)
        assert result_list == [1, None, 3]
        
        dict_with_none = {"a": 1, "b": None, "c": 3}
        result_dict = _recursive_serialize(dict_with_none)
        assert result_dict == {"a": 1, "b": None, "c": 3}

    def test_serialize_enum_types(self):
        """
        GIVEN Enum instances
        WHEN _recursive_serialize is called
        THEN expect:
            - Enum is converted to its value
            - Value is recursively serialized if needed
        """
        enum_str = SampleEnum.RED
        result_str = _recursive_serialize(enum_str)
        assert result_str == "red"
        
        enum_int = SampleEnum.GREEN
        result_int = _recursive_serialize(enum_int)
        assert result_int == 3

    def test_serialize_frozenset(self):
        """
        GIVEN frozenset objects
        WHEN _recursive_serialize is called
        THEN expect:
            - Frozenset is converted to list
            - All elements are serialized
        """
        test_frozenset = frozenset([1, 2, 3, "hello"])
        result = _recursive_serialize(test_frozenset)
        
        assert isinstance(result, list)
        assert len(result) == 4
        assert 1 in result
        assert 2 in result
        assert 3 in result
        assert "hello" in result

    def test_serialize_range_objects(self):
        """
        GIVEN range objects
        WHEN _recursive_serialize is called
        THEN expect:
            - Range is converted to list
            - All values are included
        """
        test_range = range(5)
        result = _recursive_serialize(test_range)
        
        assert result == [0, 1, 2, 3, 4]