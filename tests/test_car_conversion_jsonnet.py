"""
Test module for Jsonnet integration in car_conversion module.

This module tests the Jsonnet to/from CAR conversion methods.
"""

import os
import json
import tempfile
import pytest

try:
    import _jsonnet
    HAVE_JSONNET = True
except ImportError:
    HAVE_JSONNET = False

try:
    import pyarrow as pa
    HAVE_ARROW = True
except ImportError:
    HAVE_ARROW = False

# Mark all tests to skip if jsonnet is not available
pytestmark = pytest.mark.skipif(not HAVE_JSONNET or not HAVE_ARROW, 
                                reason="jsonnet and PyArrow libraries not available")


class TestCarConversionJsonnet:
    """Test Jsonnet to/from CAR conversion."""
    
    def test_jsonnet_to_car(self):
        """GIVEN a Jsonnet file WHEN converting to CAR THEN create valid CAR file"""
        from ipfs_datasets_py.data_transformation.serialization.car_conversion import DataInterchangeUtils
        
        converter = DataInterchangeUtils()
        
        with tempfile.TemporaryDirectory() as temp_dir:
            # Create Jsonnet file
            jsonnet_path = os.path.join(temp_dir, "input.jsonnet")
            data = [
                {"id": 1, "name": "first"},
                {"id": 2, "name": "second"},
            ]
            with open(jsonnet_path, 'w') as f:
                f.write(json.dumps(data))
            
            # Convert to CAR
            car_path = os.path.join(temp_dir, "output.car")
            root_cid = converter.jsonnet_to_car(jsonnet_path, car_path)
            
            assert isinstance(root_cid, str)
            assert len(root_cid) > 0
            assert os.path.exists(car_path)
    
    def test_jsonnet_to_car_with_ext_vars(self):
        """GIVEN Jsonnet with external vars WHEN converting to CAR THEN use provided vars"""
        from ipfs_datasets_py.data_transformation.serialization.car_conversion import DataInterchangeUtils
        
        converter = DataInterchangeUtils()
        
        with tempfile.TemporaryDirectory() as temp_dir:
            # Create Jsonnet file with external variables
            jsonnet_path = os.path.join(temp_dir, "input.jsonnet")
            with open(jsonnet_path, 'w') as f:
                f.write('''
                    local dept = std.extVar("department");
                    local count = std.parseJson(std.extVar("count"));
                    [{ id: i, department: dept } for i in std.range(1, count)]
                ''')
            
            # Convert to CAR with variables
            car_path = os.path.join(temp_dir, "output.car")
            root_cid = converter.jsonnet_to_car(
                jsonnet_path,
                car_path,
                ext_vars={"department": "Engineering", "count": "3"}
            )
            
            assert isinstance(root_cid, str)
            assert os.path.exists(car_path)
    
    def test_jsonnet_to_car_single_object(self):
        """GIVEN Jsonnet returning single object WHEN converting to CAR THEN wrap in array"""
        from ipfs_datasets_py.data_transformation.serialization.car_conversion import DataInterchangeUtils
        
        converter = DataInterchangeUtils()
        
        with tempfile.TemporaryDirectory() as temp_dir:
            # Create Jsonnet file with single object
            jsonnet_path = os.path.join(temp_dir, "input.jsonnet")
            with open(jsonnet_path, 'w') as f:
                f.write('{ id: 1, name: "single" }')
            
            # Convert to CAR
            car_path = os.path.join(temp_dir, "output.car")
            root_cid = converter.jsonnet_to_car(jsonnet_path, car_path)
            
            assert isinstance(root_cid, str)
            assert os.path.exists(car_path)
    
    def test_car_to_jsonnet(self):
        """GIVEN a CAR file WHEN converting to Jsonnet THEN create valid Jsonnet file"""
        from ipfs_datasets_py.data_transformation.serialization.car_conversion import DataInterchangeUtils
        
        converter = DataInterchangeUtils()
        
        with tempfile.TemporaryDirectory() as temp_dir:
            # Create Jsonnet file
            jsonnet_path = os.path.join(temp_dir, "input.jsonnet")
            original_data = [
                {"id": 1, "name": "first"},
                {"id": 2, "name": "second"},
            ]
            with open(jsonnet_path, 'w') as f:
                f.write(json.dumps(original_data))
            
            # Convert to CAR
            car_path = os.path.join(temp_dir, "data.car")
            converter.jsonnet_to_car(jsonnet_path, car_path)
            
            # Convert back to Jsonnet
            output_jsonnet_path = os.path.join(temp_dir, "output.jsonnet")
            result_path = converter.car_to_jsonnet(car_path, output_jsonnet_path)
            
            assert os.path.exists(result_path)
            
            # Verify content
            with open(result_path, 'r') as f:
                recovered_data = json.load(f)
            
            assert len(recovered_data) == 2
            assert recovered_data[0]["id"] == 1
            assert recovered_data[1]["name"] == "second"
    
    def test_jsonnet_to_car_with_hash_columns(self):
        """GIVEN Jsonnet and hash columns WHEN converting to CAR THEN use hash columns"""
        from ipfs_datasets_py.data_transformation.serialization.car_conversion import DataInterchangeUtils
        
        converter = DataInterchangeUtils()
        
        with tempfile.TemporaryDirectory() as temp_dir:
            # Create Jsonnet file
            jsonnet_path = os.path.join(temp_dir, "input.jsonnet")
            data = [
                {"id": 1, "name": "first", "value": 10},
                {"id": 2, "name": "second", "value": 20},
            ]
            with open(jsonnet_path, 'w') as f:
                f.write(json.dumps(data))
            
            # Convert to CAR with hash columns
            car_path = os.path.join(temp_dir, "output.car")
            root_cid = converter.jsonnet_to_car(
                jsonnet_path,
                car_path,
                hash_columns=["id"]
            )
            
            assert isinstance(root_cid, str)
            assert os.path.exists(car_path)


class TestRoundTripConversion:
    """Test round-trip conversions with Jsonnet."""
    
    def test_jsonnet_to_car_to_jsonnet_roundtrip(self):
        """GIVEN Jsonnet WHEN converting to CAR and back THEN data preserved"""
        from ipfs_datasets_py.data_transformation.serialization.car_conversion import DataInterchangeUtils
        
        converter = DataInterchangeUtils()
        
        with tempfile.TemporaryDirectory() as temp_dir:
            # Original data
            original_data = [
                {"id": 1, "name": "Alice", "value": 100.5},
                {"id": 2, "name": "Bob", "value": 200.5},
                {"id": 3, "name": "Charlie", "value": 300.5},
            ]
            
            # Create Jsonnet file
            input_jsonnet_path = os.path.join(temp_dir, "input.jsonnet")
            with open(input_jsonnet_path, 'w') as f:
                f.write(json.dumps(original_data, indent=2))
            
            # Convert to CAR
            car_path = os.path.join(temp_dir, "data.car")
            converter.jsonnet_to_car(input_jsonnet_path, car_path)
            
            # Convert back to Jsonnet
            output_jsonnet_path = os.path.join(temp_dir, "output.jsonnet")
            converter.car_to_jsonnet(car_path, output_jsonnet_path)
            
            # Read recovered data
            with open(output_jsonnet_path, 'r') as f:
                recovered_data = json.load(f)
            
            # Verify data integrity
            assert len(recovered_data) == len(original_data)
            
            for orig, recovered in zip(original_data, recovered_data):
                assert orig["id"] == recovered["id"]
                assert orig["name"] == recovered["name"]
                # Use approximate comparison for floats
                assert abs(orig["value"] - recovered["value"]) < 0.01
    
    def test_jsonnet_with_complex_data_roundtrip(self):
        """GIVEN complex Jsonnet data WHEN round-tripping through CAR THEN data preserved"""
        from ipfs_datasets_py.data_transformation.serialization.car_conversion import DataInterchangeUtils
        
        converter = DataInterchangeUtils()
        
        with tempfile.TemporaryDirectory() as temp_dir:
            # Complex data with nested structures (flattened for Arrow)
            original_data = [
                {
                    "id": 1,
                    "name": "Alice",
                    "age": 30,
                    "is_active": True,
                    "score": 95.5,
                },
                {
                    "id": 2,
                    "name": "Bob",
                    "age": 25,
                    "is_active": False,
                    "score": 87.3,
                },
            ]
            
            # Create Jsonnet file
            input_jsonnet_path = os.path.join(temp_dir, "input.jsonnet")
            with open(input_jsonnet_path, 'w') as f:
                f.write(json.dumps(original_data, indent=2))
            
            # Convert to CAR
            car_path = os.path.join(temp_dir, "data.car")
            converter.jsonnet_to_car(input_jsonnet_path, car_path)
            
            # Convert back to Jsonnet
            output_jsonnet_path = os.path.join(temp_dir, "output.jsonnet")
            converter.car_to_jsonnet(car_path, output_jsonnet_path)
            
            # Read recovered data
            with open(output_jsonnet_path, 'r') as f:
                recovered_data = json.load(f)
            
            # Verify all fields
            assert len(recovered_data) == 2
            assert recovered_data[0]["id"] == 1
            assert recovered_data[0]["name"] == "Alice"
            assert recovered_data[0]["age"] == 30
            assert recovered_data[0]["is_active"] is True
            assert abs(recovered_data[0]["score"] - 95.5) < 0.01


class TestErrorHandling:
    """Test error handling in CAR conversion."""
    
    def test_jsonnet_to_car_without_jsonnet_raises_error(self, monkeypatch):
        """GIVEN jsonnet not available WHEN converting THEN raise ImportError"""
        from ipfs_datasets_py import car_conversion
        monkeypatch.setattr(car_conversion, "HAVE_JSONNET", False)
        
        DataInterchangeUtils = car_conversion.DataInterchangeUtils
        
        converter = DataInterchangeUtils()
        
        with tempfile.TemporaryDirectory() as temp_dir:
            jsonnet_path = os.path.join(temp_dir, "test.jsonnet")
            with open(jsonnet_path, 'w') as f:
                f.write('[{ id: 1 }]')
            
            car_path = os.path.join(temp_dir, "output.car")
            
            with pytest.raises(ImportError, match="jsonnet library is required"):
                converter.jsonnet_to_car(jsonnet_path, car_path)
    
    def test_car_to_jsonnet_without_arrow_raises_error(self, monkeypatch):
        """GIVEN PyArrow not available WHEN converting THEN raise ImportError"""
        from ipfs_datasets_py import car_conversion
        monkeypatch.setattr(car_conversion, "HAVE_ARROW", False)
        
        DataInterchangeUtils = car_conversion.DataInterchangeUtils
        
        converter = DataInterchangeUtils()
        
        with tempfile.TemporaryDirectory() as temp_dir:
            car_path = os.path.join(temp_dir, "test.car")
            jsonnet_path = os.path.join(temp_dir, "output.jsonnet")
            
            # Create a mock CAR file
            with open(car_path, 'wb') as f:
                f.write(b"mock car data")
            
            with pytest.raises(ImportError, match="PyArrow is required"):
                converter.car_to_jsonnet(car_path, jsonnet_path)
