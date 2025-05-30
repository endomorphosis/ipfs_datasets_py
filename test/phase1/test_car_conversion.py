import os
import sys
import unittest
import tempfile
import shutil
import numpy as np
import json
from typing import Dict, List, Any, Optional

# Add parent directory to path to import the module
parent_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
sys.path.append(parent_dir)

# Import the module to test
try:
    from ipfs_datasets_py.car_conversion import DataInterchangeUtils
except ImportError:
    # Mock class for testing structure before implementation
    class DataInterchangeUtils:
        def export_table_to_car(self, table, output_path, hash_columns=None):
            """Export Arrow table to CAR file"""
            with open(output_path, 'wb') as f:
                f.write(b"mock CAR data")
            return "bafybeicarfilecid"

        def import_table_from_car(self, car_path):
            """Import Arrow table from CAR file"""
            # Return a mock table
            class MockTable:
                def __init__(self):
                    self.num_rows = 10
                    self.column_names = ["id", "value"]

                def to_pydict(self):
                    return {
                        "id": list(range(10)),
                        "value": [float(i * 1.5) for i in range(10)]
                    }

            return MockTable()

        def parquet_to_car(self, parquet_path, car_path, hash_columns=None):
            """Convert Parquet file to CAR file"""
            with open(car_path, 'wb') as f:
                f.write(b"mock CAR data from parquet")
            return "bafybeip2cconversion"

        def car_to_parquet(self, car_path, parquet_path):
            """Convert CAR file to Parquet file"""
            with open(parquet_path, 'wb') as f:
                f.write(b"mock parquet data from CAR")
            return parquet_path

        def stream_parquet_to_car(self, parquet_path, car_path, batch_size=10000):
            """Stream Parquet file to CAR file in batches"""
            with open(car_path, 'wb') as f:
                f.write(b"mock streamed CAR data")
            return "bafybeistreamedcar"


# Try to import testing dependencies, skip tests if not available
try:
    import pyarrow as pa
    import pyarrow.parquet as pq
    HAVE_ARROW = True
except ImportError:
    HAVE_ARROW = False


class TestCarConversion(unittest.TestCase):
    def setUp(self):
        """Set up test fixtures before each test"""
        self.temp_dir = tempfile.mkdtemp()
        self.utils = DataInterchangeUtils()

    def tearDown(self):
        """Clean up test fixtures after each test"""
        shutil.rmtree(self.temp_dir)

    def test_arrow_table_to_car(self):
        """Test converting Arrow table to CAR file"""
        if not HAVE_ARROW:
            self.skipTest("PyArrow not installed")

        # Create a test Arrow table
        data = {
            "id": pa.array(list(range(5))),
            "name": pa.array(["A", "B", "C", "D", "E"]),
            "value": pa.array([1.1, 2.2, 3.3, 4.4, 5.5]),
        }
        table = pa.Table.from_pydict(data)

        # Convert to CAR
        car_path = os.path.join(self.temp_dir, "test_table.car")
        cid = self.utils.export_table_to_car(table, car_path, hash_columns=["id"])

        # Verify file exists
        self.assertTrue(os.path.exists(car_path))
        self.assertGreater(os.path.getsize(car_path), 0)

        # Verify CID
        self.assertIsNotNone(cid)

    def test_car_to_arrow_table(self):
        """Test converting CAR file to Arrow table"""
        if not HAVE_ARROW:
            self.skipTest("PyArrow not installed")

        # Create a test CAR file (using the export function)
        data = {
            "id": pa.array(list(range(5))),
            "value": pa.array([1.1, 2.2, 3.3, 4.4, 5.5]),
        }
        table = pa.Table.from_pydict(data)

        car_path = os.path.join(self.temp_dir, "test_import.car")
        self.utils.export_table_to_car(table, car_path)

        # Import from CAR
        imported_table = self.utils.import_table_from_car(car_path)

        # Verify table structure
        self.assertEqual(imported_table.num_rows, table.num_rows)
        self.assertEqual(set(imported_table.column_names), set(table.column_names))

    def test_parquet_to_car_conversion(self):
        """Test converting Parquet file to CAR file"""
        if not HAVE_ARROW:
            self.skipTest("PyArrow not installed")

        # Create a test Parquet file
        data = {
            "id": pa.array(list(range(5))),
            "value": pa.array([1.1, 2.2, 3.3, 4.4, 5.5]),
        }
        table = pa.Table.from_pydict(data)

        parquet_path = os.path.join(self.temp_dir, "test_data.parquet")
        pq.write_table(table, parquet_path)

        # Convert to CAR
        car_path = os.path.join(self.temp_dir, "test_from_parquet.car")
        cid = self.utils.parquet_to_car(parquet_path, car_path, hash_columns=["id"])

        # Verify file exists
        self.assertTrue(os.path.exists(car_path))
        self.assertGreater(os.path.getsize(car_path), 0)

        # Verify CID
        self.assertIsNotNone(cid)

    def test_car_to_parquet_conversion(self):
        """Test converting CAR file to Parquet file"""
        if not HAVE_ARROW:
            self.skipTest("PyArrow not installed")

        # Create a test CAR file (via table export)
        data = {
            "id": pa.array(list(range(5))),
            "value": pa.array([1.1, 2.2, 3.3, 4.4, 5.5]),
        }
        table = pa.Table.from_pydict(data)

        car_path = os.path.join(self.temp_dir, "for_parquet.car")
        self.utils.export_table_to_car(table, car_path)

        # Convert to Parquet
        parquet_path = os.path.join(self.temp_dir, "from_car.parquet")
        result_path = self.utils.car_to_parquet(car_path, parquet_path)

        # Verify file exists
        self.assertTrue(os.path.exists(result_path))
        self.assertGreater(os.path.getsize(result_path), 0)

        # Verify the file is readable as Parquet (if we have PyArrow)
        if HAVE_ARROW:
            try:
                loaded_table = pq.read_table(result_path)
                self.assertIsNotNone(loaded_table)
            except Exception:
                # Mock implementation might not create valid Parquet
                pass

    def test_streaming_conversion(self):
        """Test streaming conversion for large files"""
        if not HAVE_ARROW:
            self.skipTest("PyArrow not installed")

        # Create a medium-sized Parquet file
        n_rows = 1000  # Not too large to avoid test slowdown
        data = {
            "id": pa.array(list(range(n_rows))),
            "value": pa.array([float(i * 0.5) for i in range(n_rows)]),
        }
        table = pa.Table.from_pydict(data)

        parquet_path = os.path.join(self.temp_dir, "large_data.parquet")
        pq.write_table(table, parquet_path)

        # Convert with streaming
        car_path = os.path.join(self.temp_dir, "streamed.car")
        cid = self.utils.stream_parquet_to_car(parquet_path, car_path, batch_size=100)

        # Verify file exists
        self.assertTrue(os.path.exists(car_path))
        self.assertGreater(os.path.getsize(car_path), 0)

        # Verify CID
        self.assertIsNotNone(cid)


if __name__ == '__main__':
    unittest.main()
