"""
Test module for Jsonnet conversion utilities.

This module tests the conversion between Jsonnet and other formats
(JSON, JSONL, Parquet, CAR, IPLD).
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
    import pyarrow.parquet as pq
    HAVE_ARROW = True
except ImportError:
    HAVE_ARROW = False

# Mark all tests to skip if jsonnet is not available
pytestmark = pytest.mark.skipif(not HAVE_JSONNET, reason="jsonnet library not available")


class TestJsonnetConverter:
    """Test the JsonnetConverter class."""
    
    def test_import_without_jsonnet(self):
        """GIVEN jsonnet is not available WHEN importing THEN raise ImportError"""
        if HAVE_JSONNET:
            pytest.skip("Jsonnet is available, cannot test import error")
        
        from ipfs_datasets_py.jsonnet_utils import JsonnetConverter
        
        with pytest.raises(ImportError, match="jsonnet library is required"):
            JsonnetConverter()
    
    def test_simple_jsonnet_to_json(self):
        """GIVEN a simple Jsonnet string WHEN converting to JSON THEN return valid JSON"""
        from ipfs_datasets_py.jsonnet_utils import JsonnetConverter
        
        converter = JsonnetConverter()
        jsonnet_str = '{ name: "test", value: 42 }'
        
        json_str = converter.jsonnet_to_json(jsonnet_str)
        data = json.loads(json_str)
        
        assert data["name"] == "test"
        assert data["value"] == 42
    
    def test_jsonnet_array_to_json(self):
        """GIVEN a Jsonnet array WHEN converting to JSON THEN return valid JSON array"""
        from ipfs_datasets_py.jsonnet_utils import JsonnetConverter
        
        converter = JsonnetConverter()
        jsonnet_str = '[{ id: 1, name: "first" }, { id: 2, name: "second" }]'
        
        json_str = converter.jsonnet_to_json(jsonnet_str)
        data = json.loads(json_str)
        
        assert len(data) == 2
        assert data[0]["id"] == 1
        assert data[1]["name"] == "second"
    
    def test_jsonnet_with_external_vars(self):
        """GIVEN Jsonnet with external variables WHEN evaluating THEN use provided variables"""
        from ipfs_datasets_py.jsonnet_utils import JsonnetConverter
        
        converter = JsonnetConverter()
        jsonnet_str = '{ name: std.extVar("name"), age: std.parseJson(std.extVar("age")) }'
        
        json_str = converter.jsonnet_to_json(
            jsonnet_str,
            ext_vars={"name": "Alice", "age": "30"}
        )
        data = json.loads(json_str)
        
        assert data["name"] == "Alice"
        assert data["age"] == 30
    
    def test_jsonnet_with_tla_vars(self):
        """GIVEN Jsonnet with TLA variables WHEN evaluating THEN use provided TLA vars"""
        from ipfs_datasets_py.jsonnet_utils import JsonnetConverter
        
        converter = JsonnetConverter()
        # TLA (Top-Level Arguments) are function parameters
        jsonnet_str = 'function(name, age) { name: name, age: age }'
        
        json_str = converter.jsonnet_to_json(
            jsonnet_str,
            tla_vars={"name": "Bob", "age": "25"}
        )
        data = json.loads(json_str)
        
        assert data["name"] == "Bob"
        assert data["age"] == "25"  # TLA vars are passed as strings
    
    def test_jsonnet_file_to_json(self):
        """GIVEN a Jsonnet file WHEN converting to JSON THEN return valid JSON"""
        from ipfs_datasets_py.jsonnet_utils import JsonnetConverter
        
        converter = JsonnetConverter()
        
        with tempfile.TemporaryDirectory() as temp_dir:
            # Create sample Jsonnet file
            jsonnet_path = os.path.join(temp_dir, "test.jsonnet")
            with open(jsonnet_path, 'w') as f:
                f.write('{ name: "test", items: [1, 2, 3] }')
            
            json_str = converter.jsonnet_file_to_json(jsonnet_path)
            data = json.loads(json_str)
            
            assert data["name"] == "test"
            assert len(data["items"]) == 3
    
    def test_jsonnet_to_dict(self):
        """GIVEN a Jsonnet string WHEN converting to dict THEN return Python dict"""
        from ipfs_datasets_py.jsonnet_utils import JsonnetConverter
        
        converter = JsonnetConverter()
        jsonnet_str = '{ name: "test", value: 42 }'
        
        data = converter.jsonnet_to_dict(jsonnet_str)
        
        assert isinstance(data, dict)
        assert data["name"] == "test"
        assert data["value"] == 42
    
    def test_json_to_jsonnet(self):
        """GIVEN a JSON string WHEN converting to Jsonnet THEN return valid Jsonnet"""
        from ipfs_datasets_py.jsonnet_utils import JsonnetConverter
        
        converter = JsonnetConverter()
        json_str = '{"name": "test", "value": 42}'
        
        jsonnet_str = converter.json_to_jsonnet(json_str)
        
        # Verify it's valid by evaluating it back
        json_result = converter.jsonnet_to_json(jsonnet_str)
        data = json.loads(json_result)
        
        assert data["name"] == "test"
        assert data["value"] == 42
    
    def test_dict_to_jsonnet(self):
        """GIVEN a Python dict WHEN converting to Jsonnet THEN return valid Jsonnet"""
        from ipfs_datasets_py.jsonnet_utils import JsonnetConverter
        
        converter = JsonnetConverter()
        data = {"name": "test", "value": 42}
        
        jsonnet_str = converter.dict_to_jsonnet(data)
        
        # Verify it's valid by evaluating it back
        json_result = converter.jsonnet_to_json(jsonnet_str)
        result_data = json.loads(json_result)
        
        assert result_data["name"] == "test"
        assert result_data["value"] == 42


class TestJsonnetToJsonl:
    """Test Jsonnet to JSONL conversion."""
    
    def test_jsonnet_array_to_jsonl(self):
        """GIVEN a Jsonnet array WHEN converting to JSONL THEN create valid JSONL file"""
        from ipfs_datasets_py.jsonnet_utils import JsonnetConverter
        
        converter = JsonnetConverter()
        jsonnet_str = '[{ id: 1, name: "first" }, { id: 2, name: "second" }]'
        
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = os.path.join(temp_dir, "output.jsonl")
            result_path = converter.jsonnet_to_jsonl(jsonnet_str, output_path)
            
            assert os.path.exists(result_path)
            
            # Read and verify
            with open(result_path, 'r') as f:
                lines = f.readlines()
            
            assert len(lines) == 2
            
            record1 = json.loads(lines[0])
            assert record1["id"] == 1
            assert record1["name"] == "first"
            
            record2 = json.loads(lines[1])
            assert record2["id"] == 2
            assert record2["name"] == "second"
    
    def test_jsonnet_non_array_to_jsonl_raises_error(self):
        """GIVEN a Jsonnet object (not array) WHEN converting to JSONL THEN raise ValueError"""
        from ipfs_datasets_py.jsonnet_utils import JsonnetConverter
        
        converter = JsonnetConverter()
        jsonnet_str = '{ id: 1, name: "single" }'
        
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = os.path.join(temp_dir, "output.jsonl")
            
            with pytest.raises(ValueError, match="must evaluate to an array"):
                converter.jsonnet_to_jsonl(jsonnet_str, output_path)
    
    def test_jsonnet_file_to_jsonl(self):
        """GIVEN a Jsonnet file with array WHEN converting to JSONL THEN create valid JSONL"""
        from ipfs_datasets_py.jsonnet_utils import JsonnetConverter
        
        converter = JsonnetConverter()
        
        with tempfile.TemporaryDirectory() as temp_dir:
            # Create Jsonnet file
            jsonnet_path = os.path.join(temp_dir, "input.jsonnet")
            with open(jsonnet_path, 'w') as f:
                f.write('[{ id: i } for i in std.range(0, 4)]')
            
            output_path = os.path.join(temp_dir, "output.jsonl")
            result_path = converter.jsonnet_file_to_jsonl(jsonnet_path, output_path)
            
            assert os.path.exists(result_path)
            
            # Read and verify
            with open(result_path, 'r') as f:
                lines = f.readlines()
            
            assert len(lines) == 5  # 0 to 4 inclusive


class TestJsonlToJsonnet:
    """Test JSONL to Jsonnet conversion."""
    
    def test_jsonl_to_jsonnet(self):
        """GIVEN a JSONL file WHEN converting to Jsonnet THEN create valid Jsonnet"""
        from ipfs_datasets_py.jsonnet_utils import JsonnetConverter
        
        converter = JsonnetConverter()
        
        with tempfile.TemporaryDirectory() as temp_dir:
            # Create JSONL file
            jsonl_path = os.path.join(temp_dir, "input.jsonl")
            records = [
                {"id": 1, "name": "first"},
                {"id": 2, "name": "second"},
                {"id": 3, "name": "third"},
            ]
            with open(jsonl_path, 'w') as f:
                for record in records:
                    f.write(json.dumps(record) + '\n')
            
            output_path = os.path.join(temp_dir, "output.jsonnet")
            result_path = converter.jsonl_to_jsonnet(jsonl_path, output_path)
            
            assert os.path.exists(result_path)
            
            # Verify by reading back
            data = converter.jsonnet_file_to_dict(result_path)
            
            assert len(data) == 3
            assert data[0]["id"] == 1
            assert data[2]["name"] == "third"
    
    def test_jsonl_to_jsonnet_string(self):
        """GIVEN a JSONL file WHEN converting without output path THEN return Jsonnet string"""
        from ipfs_datasets_py.jsonnet_utils import JsonnetConverter
        
        converter = JsonnetConverter()
        
        with tempfile.TemporaryDirectory() as temp_dir:
            # Create JSONL file
            jsonl_path = os.path.join(temp_dir, "input.jsonl")
            records = [{"id": 1}, {"id": 2}]
            with open(jsonl_path, 'w') as f:
                for record in records:
                    f.write(json.dumps(record) + '\n')
            
            jsonnet_str = converter.jsonl_to_jsonnet(jsonl_path)
            
            assert isinstance(jsonnet_str, str)
            
            # Verify by evaluating
            data = converter.jsonnet_to_dict(jsonnet_str)
            assert len(data) == 2


@pytest.mark.skipif(not HAVE_ARROW, reason="PyArrow not available")
class TestJsonnetToArrowParquet:
    """Test Jsonnet to Arrow/Parquet conversion."""
    
    def test_jsonnet_to_arrow(self):
        """GIVEN a Jsonnet array WHEN converting to Arrow THEN return valid Arrow table"""
        from ipfs_datasets_py.jsonnet_utils import JsonnetConverter
        
        converter = JsonnetConverter()
        jsonnet_str = '[{ id: 1, name: "first", value: 10.5 }, { id: 2, name: "second", value: 20.5 }]'
        
        table = converter.jsonnet_to_arrow(jsonnet_str)
        
        assert table.num_rows == 2
        assert len(table.column_names) == 3
        assert "id" in table.column_names
        assert "name" in table.column_names
        assert "value" in table.column_names
    
    def test_jsonnet_file_to_arrow(self):
        """GIVEN a Jsonnet file WHEN converting to Arrow THEN return valid Arrow table"""
        from ipfs_datasets_py.jsonnet_utils import JsonnetConverter
        
        converter = JsonnetConverter()
        
        with tempfile.TemporaryDirectory() as temp_dir:
            jsonnet_path = os.path.join(temp_dir, "input.jsonnet")
            with open(jsonnet_path, 'w') as f:
                f.write('[{ id: i, value: i * 10 } for i in std.range(1, 5)]')
            
            table = converter.jsonnet_file_to_arrow(jsonnet_path)
            
            assert table.num_rows == 5
            assert len(table.column_names) == 2
    
    def test_jsonnet_to_parquet(self):
        """GIVEN a Jsonnet array WHEN converting to Parquet THEN create valid Parquet file"""
        from ipfs_datasets_py.jsonnet_utils import JsonnetConverter
        
        converter = JsonnetConverter()
        jsonnet_str = '[{ id: 1, name: "first" }, { id: 2, name: "second" }]'
        
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = os.path.join(temp_dir, "output.parquet")
            result_path = converter.jsonnet_to_parquet(jsonnet_str, output_path)
            
            assert os.path.exists(result_path)
            
            # Read and verify
            table = pq.read_table(result_path)
            assert table.num_rows == 2
            assert len(table.column_names) == 2
    
    def test_jsonnet_file_to_parquet(self):
        """GIVEN a Jsonnet file WHEN converting to Parquet THEN create valid Parquet file"""
        from ipfs_datasets_py.jsonnet_utils import JsonnetConverter
        
        converter = JsonnetConverter()
        
        with tempfile.TemporaryDirectory() as temp_dir:
            jsonnet_path = os.path.join(temp_dir, "input.jsonnet")
            with open(jsonnet_path, 'w') as f:
                f.write('[{ id: i } for i in std.range(1, 10)]')
            
            output_path = os.path.join(temp_dir, "output.parquet")
            result_path = converter.jsonnet_file_to_parquet(jsonnet_path, output_path)
            
            assert os.path.exists(result_path)
            
            # Read and verify
            table = pq.read_table(result_path)
            assert table.num_rows == 10


class TestConvenienceFunctions:
    """Test convenience functions."""
    
    def test_jsonnet_to_json_function(self):
        """GIVEN convenience function WHEN converting Jsonnet to JSON THEN work correctly"""
        from ipfs_datasets_py.jsonnet_utils import jsonnet_to_json
        
        jsonnet_str = '{ name: "test" }'
        json_str = jsonnet_to_json(jsonnet_str)
        data = json.loads(json_str)
        
        assert data["name"] == "test"
    
    def test_jsonnet_to_jsonl_function(self):
        """GIVEN convenience function WHEN converting Jsonnet to JSONL THEN work correctly"""
        from ipfs_datasets_py.jsonnet_utils import jsonnet_to_jsonl
        
        jsonnet_str = '[{ id: 1 }, { id: 2 }]'
        
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = os.path.join(temp_dir, "output.jsonl")
            result_path = jsonnet_to_jsonl(jsonnet_str, output_path)
            
            assert os.path.exists(result_path)
    
    def test_jsonl_to_jsonnet_function(self):
        """GIVEN convenience function WHEN converting JSONL to Jsonnet THEN work correctly"""
        from ipfs_datasets_py.jsonnet_utils import jsonl_to_jsonnet
        
        with tempfile.TemporaryDirectory() as temp_dir:
            jsonl_path = os.path.join(temp_dir, "input.jsonl")
            with open(jsonl_path, 'w') as f:
                f.write('{"id": 1}\n{"id": 2}\n')
            
            jsonnet_str = jsonl_to_jsonnet(jsonl_path)
            assert isinstance(jsonnet_str, str)


class TestErrorHandling:
    """Test error handling."""
    
    def test_invalid_jsonnet_syntax(self):
        """GIVEN invalid Jsonnet syntax WHEN evaluating THEN raise RuntimeError"""
        from ipfs_datasets_py.jsonnet_utils import JsonnetConverter
        
        converter = JsonnetConverter()
        invalid_jsonnet = '{ name: invalid syntax }'  # Missing quotes
        
        with pytest.raises(RuntimeError, match="Failed to evaluate Jsonnet"):
            converter.jsonnet_to_json(invalid_jsonnet)
    
    def test_jsonnet_file_not_found(self):
        """GIVEN non-existent file WHEN evaluating THEN raise FileNotFoundError"""
        from ipfs_datasets_py.jsonnet_utils import JsonnetConverter
        
        converter = JsonnetConverter()
        
        with pytest.raises(FileNotFoundError):
            converter.jsonnet_file_to_json("/nonexistent/file.jsonnet")
