"""
Test module for Jsonnet integration in dataset_serialization module.

This module tests the Jsonnet conversion methods in DatasetSerializer.
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


class TestDatasetSerializerJsonnet:
    """Test Jsonnet methods in DatasetSerializer."""
    
    def test_import_from_jsonnet(self):
        """GIVEN a Jsonnet file WHEN importing THEN return Arrow table"""
        from ipfs_datasets_py.dataset_serialization import DatasetSerializer
        
        serializer = DatasetSerializer()
        
        with tempfile.TemporaryDirectory() as temp_dir:
            # Create Jsonnet file
            jsonnet_path = os.path.join(temp_dir, "test.jsonnet")
            with open(jsonnet_path, 'w') as f:
                f.write('[{ id: 1, name: "first" }, { id: 2, name: "second" }]')
            
            table = serializer.import_from_jsonnet(jsonnet_path)
            
            assert table.num_rows == 2
            assert len(table.column_names) == 2
            assert "id" in table.column_names
            assert "name" in table.column_names
    
    def test_import_from_jsonnet_with_ext_vars(self):
        """GIVEN Jsonnet with external vars WHEN importing THEN use provided vars"""
        from ipfs_datasets_py.dataset_serialization import DatasetSerializer
        
        serializer = DatasetSerializer()
        
        with tempfile.TemporaryDirectory() as temp_dir:
            jsonnet_path = os.path.join(temp_dir, "test.jsonnet")
            with open(jsonnet_path, 'w') as f:
                f.write('''
                    local dept = std.extVar("department");
                    [{ id: 1, department: dept }, { id: 2, department: dept }]
                ''')
            
            table = serializer.import_from_jsonnet(
                jsonnet_path,
                ext_vars={"department": "Engineering"}
            )
            
            assert table.num_rows == 2
            
            # Verify department value
            df = table.to_pandas()
            assert df["department"][0] == "Engineering"
    
    def test_import_from_jsonnet_single_object(self):
        """GIVEN Jsonnet returning single object WHEN importing THEN wrap in array"""
        from ipfs_datasets_py.dataset_serialization import DatasetSerializer
        
        serializer = DatasetSerializer()
        
        with tempfile.TemporaryDirectory() as temp_dir:
            jsonnet_path = os.path.join(temp_dir, "test.jsonnet")
            with open(jsonnet_path, 'w') as f:
                f.write('{ id: 1, name: "single" }')
            
            table = serializer.import_from_jsonnet(jsonnet_path)
            
            assert table.num_rows == 1
            assert len(table.column_names) == 2
    
    def test_convert_jsonnet_to_arrow(self):
        """GIVEN Jsonnet string WHEN converting to Arrow THEN return table"""
        from ipfs_datasets_py.dataset_serialization import DatasetSerializer
        
        serializer = DatasetSerializer()
        jsonnet_str = '[{ id: 1, value: 10 }, { id: 2, value: 20 }]'
        
        table = serializer.convert_jsonnet_to_arrow(jsonnet_str)
        
        assert table.num_rows == 2
        assert len(table.column_names) == 2
    
    def test_export_to_jsonnet(self):
        """GIVEN data list WHEN exporting to Jsonnet THEN create valid file"""
        from ipfs_datasets_py.dataset_serialization import DatasetSerializer
        
        serializer = DatasetSerializer()
        data = [
            {"id": 1, "name": "first"},
            {"id": 2, "name": "second"},
        ]
        
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = os.path.join(temp_dir, "output.jsonnet")
            result_path = serializer.export_to_jsonnet(data, output_path)
            
            assert os.path.exists(result_path)
            
            # Verify by reading back
            with open(result_path, 'r') as f:
                content = f.read()
            
            # Parse as JSON (Jsonnet is superset of JSON)
            parsed_data = json.loads(content)
            assert len(parsed_data) == 2
            assert parsed_data[0]["id"] == 1
    
    def test_serialize_jsonnet(self):
        """GIVEN Jsonnet file WHEN serializing to IPLD THEN return CID"""
        from ipfs_datasets_py.dataset_serialization import DatasetSerializer
        
        serializer = DatasetSerializer()
        
        with tempfile.TemporaryDirectory() as temp_dir:
            jsonnet_path = os.path.join(temp_dir, "test.jsonnet")
            with open(jsonnet_path, 'w') as f:
                f.write('[{ id: 1 }, { id: 2 }]')
            
            cid = serializer.serialize_jsonnet(jsonnet_path)
            
            assert isinstance(cid, str)
            assert len(cid) > 0
    
    def test_serialize_and_deserialize_jsonnet(self):
        """GIVEN Jsonnet data WHEN serializing and deserializing THEN data preserved"""
        from ipfs_datasets_py.dataset_serialization import DatasetSerializer
        
        serializer = DatasetSerializer()
        
        with tempfile.TemporaryDirectory() as temp_dir:
            # Create and serialize
            jsonnet_path = os.path.join(temp_dir, "input.jsonnet")
            original_data = [{"id": 1, "name": "test"}]
            
            with open(jsonnet_path, 'w') as f:
                f.write(json.dumps(original_data))
            
            cid = serializer.serialize_jsonnet(jsonnet_path)
            
            # Deserialize
            recovered_data = serializer.deserialize_jsonnet(cid)
            
            assert recovered_data == original_data
    
    def test_deserialize_jsonnet_to_file(self):
        """GIVEN serialized Jsonnet WHEN deserializing to file THEN create file"""
        from ipfs_datasets_py.dataset_serialization import DatasetSerializer
        
        serializer = DatasetSerializer()
        
        with tempfile.TemporaryDirectory() as temp_dir:
            # Serialize
            jsonnet_path = os.path.join(temp_dir, "input.jsonnet")
            data = [{"id": 1}, {"id": 2}]
            
            with open(jsonnet_path, 'w') as f:
                f.write(json.dumps(data))
            
            cid = serializer.serialize_jsonnet(jsonnet_path)
            
            # Deserialize to file
            output_path = os.path.join(temp_dir, "output.jsonnet")
            result_path = serializer.deserialize_jsonnet(cid, output_path)
            
            assert os.path.exists(result_path)
            
            # Verify content
            with open(result_path, 'r') as f:
                content = json.load(f)
            
            assert content == data
    
    def test_deserialize_wrong_type_raises_error(self):
        """GIVEN non-Jsonnet dataset CID WHEN deserializing THEN raise ValueError"""
        from ipfs_datasets_py.dataset_serialization import DatasetSerializer
        
        serializer = DatasetSerializer()
        
        with tempfile.TemporaryDirectory() as temp_dir:
            # Create a JSONL dataset (not Jsonnet)
            jsonl_path = os.path.join(temp_dir, "data.jsonl")
            with open(jsonl_path, 'w') as f:
                f.write('{"id": 1}\n')
            
            cid = serializer.serialize_jsonl(jsonl_path)
            
            # Try to deserialize as Jsonnet
            with pytest.raises(ValueError, match="does not contain a Jsonnet dataset"):
                serializer.deserialize_jsonnet(cid)


class TestJsonnetIntegrationWithOtherFormats:
    """Test Jsonnet integration with other format conversions."""
    
    def test_jsonnet_to_arrow_to_parquet(self):
        """GIVEN Jsonnet WHEN converting through Arrow to Parquet THEN data preserved"""
        from ipfs_datasets_py.dataset_serialization import DatasetSerializer
        import pyarrow.parquet as pq
        
        serializer = DatasetSerializer()
        
        with tempfile.TemporaryDirectory() as temp_dir:
            # Create Jsonnet file
            jsonnet_path = os.path.join(temp_dir, "input.jsonnet")
            original_data = [
                {"id": 1, "name": "first", "value": 10.5},
                {"id": 2, "name": "second", "value": 20.5},
            ]
            
            with open(jsonnet_path, 'w') as f:
                f.write(json.dumps(original_data))
            
            # Convert to Arrow
            table = serializer.import_from_jsonnet(jsonnet_path)
            
            # Write to Parquet
            parquet_path = os.path.join(temp_dir, "output.parquet")
            pq.write_table(table, parquet_path)
            
            # Read back and verify
            recovered_table = pq.read_table(parquet_path)
            recovered_data = recovered_table.to_pylist()
            
            assert len(recovered_data) == 2
            assert recovered_data[0]["id"] == 1
            assert recovered_data[1]["name"] == "second"
            assert abs(recovered_data[1]["value"] - 20.5) < 0.01
    
    def test_jsonnet_with_comprehensions(self):
        """GIVEN Jsonnet with array comprehensions WHEN evaluating THEN work correctly"""
        from ipfs_datasets_py.dataset_serialization import DatasetSerializer
        
        serializer = DatasetSerializer()
        
        with tempfile.TemporaryDirectory() as temp_dir:
            jsonnet_path = os.path.join(temp_dir, "test.jsonnet")
            with open(jsonnet_path, 'w') as f:
                f.write('''
                    [{ id: i, square: i * i } for i in std.range(1, 5)]
                ''')
            
            table = serializer.import_from_jsonnet(jsonnet_path)
            
            assert table.num_rows == 5
            
            df = table.to_pandas()
            assert df["id"].tolist() == [1, 2, 3, 4, 5]
            assert df["square"].tolist() == [1, 4, 9, 16, 25]


class TestErrorHandling:
    """Test error handling in Jsonnet serialization."""
    
    def test_import_without_jsonnet_raises_error(self):
        """GIVEN jsonnet not available WHEN importing THEN raise ImportError"""
        if HAVE_JSONNET:
            pytest.skip("Jsonnet is available, cannot test import error")
        
        from ipfs_datasets_py.dataset_serialization import DatasetSerializer
        
        serializer = DatasetSerializer()
        
        with tempfile.TemporaryDirectory() as temp_dir:
            jsonnet_path = os.path.join(temp_dir, "test.jsonnet")
            with open(jsonnet_path, 'w') as f:
                f.write('[{ id: 1 }]')
            
            with pytest.raises(ImportError, match="jsonnet library is required"):
                serializer.import_from_jsonnet(jsonnet_path)
    
    def test_serialize_without_jsonnet_raises_error(self):
        """GIVEN jsonnet not available WHEN serializing THEN raise ImportError"""
        if HAVE_JSONNET:
            pytest.skip("Jsonnet is available, cannot test import error")
        
        from ipfs_datasets_py.dataset_serialization import DatasetSerializer
        
        serializer = DatasetSerializer()
        
        with tempfile.TemporaryDirectory() as temp_dir:
            jsonnet_path = os.path.join(temp_dir, "test.jsonnet")
            with open(jsonnet_path, 'w') as f:
                f.write('[{ id: 1 }]')
            
            with pytest.raises(ImportError, match="jsonnet library is required"):
                serializer.serialize_jsonnet(jsonnet_path)
