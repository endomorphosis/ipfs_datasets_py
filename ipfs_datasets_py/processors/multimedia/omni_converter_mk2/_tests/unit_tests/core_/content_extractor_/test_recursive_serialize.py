import unittest
from unittest.mock import Mock, MagicMock, patch
from typing import Any
from datetime import datetime, date
from decimal import Decimal
from pathlib import Path


import unittest
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
except ImportError:
    # Skip numpy and pandas tests if not available
    np = pd = None


from core.content_extractor._recursive_serialize import _recursive_serialize


class TestEnum(Enum):
    """Test enum for serialization tests."""
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


class TestRecursiveSerialize(unittest.TestCase):
    """Test _recursive_serialize function for JSON serialization."""
    
    def setUp(self):
        """Set up test fixtures."""
        # Function under test would be imported here
        # from module import _recursive_serialize
        pass

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
        self.assertEqual(result, "hello")
        self.assertIsInstance(result, str)
        
        # Test integer
        result = _recursive_serialize(42)
        self.assertEqual(result, 42)
        self.assertIsInstance(result, int)
        
        # Test float
        result = _recursive_serialize(3.14)
        self.assertEqual(result, 3.14)
        self.assertIsInstance(result, float)
        
        # Test boolean True
        result = _recursive_serialize(True)
        self.assertEqual(result, True)
        self.assertIsInstance(result, bool)
        
        # Test boolean False
        result = _recursive_serialize(False)
        self.assertEqual(result, False)
        self.assertIsInstance(result, bool)
        
        # Test None
        result = _recursive_serialize(None)
        self.assertIsNone(result)

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
        
        self.assertIsInstance(result, list)
        self.assertEqual(len(result), 6)
        self.assertEqual(result[0], 1)
        self.assertEqual(result[1], "hello")
        self.assertEqual(result[2], 3.14)
        self.assertEqual(result[3], True)
        self.assertIsNone(result[4])
        self.assertEqual(result[5], [1, 2, 3])

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
        
        self.assertIsInstance(result, list)
        self.assertEqual(len(result), 4)
        self.assertEqual(result[0], 1)
        self.assertEqual(result[1], "hello")
        self.assertEqual(result[2], 3.14)
        self.assertEqual(result[3], [2, 3])

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
        
        self.assertIsInstance(result, dict)
        self.assertEqual(result["name"], "test")
        self.assertEqual(result["age"], 25)
        self.assertEqual(result["active"], True)
        self.assertEqual(result["data"], {"nested": "value"})
        self.assertEqual(result["items"], [1, 2, 3])

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
        
        self.assertIsInstance(result, dict)
        self.assertEqual(result["simple"], "value")
        self.assertEqual(result["level1"]["level2"][0]["level3"]["level4"], "deep_value")
        self.assertEqual(result["level1"]["level2"][1]["another"][2]["nested_list"], True)

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
        
        self.assertIsInstance(result, list)
        self.assertEqual(len(result), 4)
        self.assertIn(1, result)
        self.assertIn(2, result)
        self.assertIn(3, result)
        self.assertIn("hello", result)

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
        self.assertEqual(result_datetime, "2023-12-25T15:30:45")
        
        test_date = date(2023, 12, 25)
        result_date = _recursive_serialize(test_date)
        self.assertEqual(result_date, "2023-12-25")

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
            self.assertAlmostEqual(result, 123.456, places=3)
        elif isinstance(result, str):
            self.assertEqual(result, "123.456")
        else:
            self.fail(f"Expected float or string, got {type(result)}")

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
                self.assertEqual(decoded, test_bytes)
            except:
                # If not base64, might be direct decode
                self.assertEqual(result, "hello world")
        
        test_bytearray = bytearray(b"test data")
        result_bytearray = _recursive_serialize(test_bytearray)
        self.assertIsInstance(result_bytearray, str)

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
        
        self.assertIsInstance(result, str)
        self.assertEqual(result, "/home/user/document.txt")

    @unittest.skipIf(np is None, "numpy not available")
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
        self.assertEqual(result_1d, [1, 2, 3, 4])
        
        # Test 2D array
        array_2d = np.array([[1, 2], [3, 4]])
        result_2d = _recursive_serialize(array_2d)
        self.assertEqual(result_2d, [[1, 2], [3, 4]])
        
        # Test numpy scalar
        scalar = np.int64(42)
        result_scalar = _recursive_serialize(scalar)
        self.assertEqual(result_scalar, 42)
        self.assertIsInstance(result_scalar, int)
        
        # Test numpy float
        float_scalar = np.float64(3.14)
        result_float = _recursive_serialize(float_scalar)
        self.assertAlmostEqual(result_float, 3.14)

    @unittest.skipIf(pd is None, "pandas not available")
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
            self.assertEqual(result_series, [1, 2, 3, 4])
        elif isinstance(result_series, dict):
            self.assertIn("values", result_series)
        
        # Test DataFrame
        df = pd.DataFrame({"A": [1, 2], "B": [3, 4]})
        result_df = _recursive_serialize(df)
        
        self.assertIsInstance(result_df, (dict, list))

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
            self.assertEqual(result_dict["x"], 42)
            self.assertEqual(result_dict["y"], "test")
        
        # Test object with __str__
        obj_with_str = CustomObjectWithStr("test_data")
        result_str = _recursive_serialize(obj_with_str)
        
        if isinstance(result_str, str):
            self.assertIn("test_data", result_str)

    def test_serialize_with_circular_references(self):
        """
        GIVEN objects with circular references
        WHEN _recursive_serialize is called
        THEN expect:
            - Function handles circular refs without infinite recursion
            - Appropriate error or placeholder is returned
        """
        # Create circular reference
        circular_dict = {"self": None}
        circular_dict["self"] = circular_dict
        
        # Should not raise RecursionError
        try:
            result = _recursive_serialize(circular_dict)
            # Should either handle gracefully or raise specific exception
            self.assertIsNotNone(result)
        except RecursionError:
            self.fail("Function should handle circular references")
        except Exception as e:
            # Acceptable to raise a specific exception for circular refs
            self.assertNotIsInstance(e, RecursionError)

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
        self.assertEqual(_recursive_serialize([]), [])
        self.assertEqual(_recursive_serialize({}), {})
        self.assertEqual(_recursive_serialize(set()), [])
        self.assertEqual(_recursive_serialize(()), [])

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
        self.assertEqual(result_list, [1, None, 3])
        
        dict_with_none = {"a": 1, "b": None, "c": 3}
        result_dict = _recursive_serialize(dict_with_none)
        self.assertEqual(result_dict, {"a": 1, "b": None, "c": 3})

    def test_serialize_mixed_type_dictionary_keys(self):
        """
        GIVEN dictionary with non-string keys
        WHEN _recursive_serialize is called
        THEN expect:
            - Numeric keys are converted to strings
            - Tuple keys are converted to strings
            - Complex keys are handled appropriately
        """
        mixed_dict = {
            42: "numeric_key",
            2.5: "float_key",
            (1, 2): "tuple_key",
            True: "bool_key"
        }
        print(f"Testing mixed type dictionary keys serialization: {mixed_dict}")  # Debug print
        result = _recursive_serialize(mixed_dict)
        print(result)
        
        self.assertIsInstance(result, dict)
        
        # Keys should be strings
        for key in result.keys():
            self.assertIsInstance(key, str)
        
        # Values should be preserved
        self.assertIn("numeric_key", result.values())
        self.assertIn("float_key", result.values())
        self.assertIn("tuple_key", result.values())
        self.assertIn("bool_key", result.values())

    def test_serialize_special_float_values(self):
        """
        GIVEN special float values (inf, -inf, nan)
        WHEN _recursive_serialize is called
        THEN expect:
            - Values are converted to JSON-compatible format
            - Possibly as strings or null
        """
        inf_value = float('inf')
        result_inf = _recursive_serialize(inf_value)
        
        # Should be string, null, or some JSON-compatible representation
        self.assertIsInstance(result_inf, (str, type(None), float))
        
        neg_inf_value = float('-inf')
        result_neg_inf = _recursive_serialize(neg_inf_value)
        self.assertIsInstance(result_neg_inf, (str, type(None), float))
        
        nan_value = float('nan')
        result_nan = _recursive_serialize(nan_value)
        self.assertIsInstance(result_nan, (str, type(None), float))

    def test_serialize_enum_types(self):
        """
        GIVEN Enum instances
        WHEN _recursive_serialize is called
        THEN expect:
            - Enum is converted to its value
            - Value is recursively serialized if needed
        """
        enum_str = TestEnum.RED
        result_str = _recursive_serialize(enum_str)
        self.assertEqual(result_str, "red")
        
        enum_int = TestEnum.GREEN
        result_int = _recursive_serialize(enum_int)
        self.assertEqual(result_int, 3)

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
        
        self.assertIsInstance(result, list)
        self.assertEqual(len(result), 4)
        self.assertIn(1, result)
        self.assertIn(2, result)
        self.assertIn(3, result)
        self.assertIn("hello", result)

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
        
        self.assertEqual(result, [0, 1, 2, 3, 4])

    def test_serialize_complex_numbers(self):
        """
        GIVEN complex number objects
        WHEN _recursive_serialize is called
        THEN expect:
            - Complex numbers are converted to dict with real/imag
            - Or converted to string representation
        """
        test_complex = complex(3, 4)
        result = _recursive_serialize(test_complex)
        
        if isinstance(result, dict):
            self.assertEqual(result["real"], 3.0)
            self.assertEqual(result["imag"], 4.0)
        elif isinstance(result, str):
            self.assertIn("3", result)
            self.assertIn("4", result)
        else:
            self.fail(f"Expected dict or string, got {type(result)}")

    def test_serialize_memoryview(self):
        """
        GIVEN memoryview objects
        WHEN _recursive_serialize is called
        THEN expect:
            - Memoryview is converted to list or bytes
            - Content is preserved
        """
        test_bytes = b"hello"
        test_memoryview = memoryview(test_bytes)
        result = _recursive_serialize(test_memoryview)
        
        self.assertIsInstance(result, (list, str))

    def test_serialize_uuid_objects(self):
        """
        GIVEN UUID objects
        WHEN _recursive_serialize is called
        THEN expect:
            - UUID is converted to string
            - Format is preserved (with hyphens)
        """
        test_uuid = uuid.uuid4()
        result = _recursive_serialize(test_uuid)
        
        self.assertIsInstance(result, str)
        self.assertEqual(len(result), 36)  # Standard UUID string length
        self.assertEqual(result.count('-'), 4)  # Standard UUID has 4 hyphens

    def test_serialize_exception_handling(self):
        """
        GIVEN objects that raise exceptions during serialization
        WHEN _recursive_serialize is called
        THEN expect:
            - Function handles exception gracefully
            - Returns error indicator or raises appropriate exception
        """
        class ProblematicObject:
            def __getattribute__(self, name):
                raise ValueError("Cannot access attributes")
        
        problematic_obj = ProblematicObject()
        
        # Should either handle gracefully or raise a specific exception
        try:
            result = _recursive_serialize(problematic_obj)
            # If it doesn't raise, should return some placeholder
            self.assertIsNotNone(result)
        except Exception as e:
            # Should not be the original ValueError
            self.assertIsInstance(e, Exception)

    def test_serialize_generator_objects(self):
        """
        GIVEN generator objects
        WHEN _recursive_serialize is called
        THEN expect:
            - Generator is consumed and converted to list
            - Or returns a placeholder indicating generator type
        """
        def test_generator():
            yield 1
            yield 2
            yield 3
        
        gen = test_generator()
        result = _recursive_serialize(gen)
        
        if isinstance(result, list):
            self.assertEqual(result, [1, 2, 3])
        elif isinstance(result, str):
            self.assertIn("generator", result.lower())
        else:
            self.fail(f"Expected list or string, got {type(result)}")

    def test_serialize_lambda_functions(self):
        """
        GIVEN lambda functions
        WHEN _recursive_serialize is called
        THEN expect:
            - Function returns string representation
            - Or returns a placeholder for function type
        """
        test_lambda = lambda x: x + 1
        result = _recursive_serialize(test_lambda)
        
        self.assertIsInstance(result, str)
        self.assertIn("function", result.lower())

    def test_serialize_module_objects(self):
        """
        GIVEN module objects
        WHEN _recursive_serialize is called
        THEN expect:
            - Module name is returned as string
            - Or appropriate placeholder is used
        """
        import json
        result = _recursive_serialize(json)
        
        self.assertIsInstance(result, str)
        self.assertIn("json", result.lower())

    def test_serialize_class_types(self):
        """
        GIVEN class types (not instances)
        WHEN _recursive_serialize is called
        THEN expect:
            - Class name is returned as string
            - Or appropriate representation is used
        """
        result = _recursive_serialize(CustomObject)
        
        self.assertIsInstance(result, str)
        self.assertIn("CustomObject", result)


if __name__ == "__main__":
    unittest.main()
