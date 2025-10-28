"""
Example of using the Jsonnet conversion utilities.

This script demonstrates how to use the Jsonnet conversion utilities
for converting data between Jsonnet and other formats (JSONL, Parquet, CAR, IPLD).
"""

import os
import sys
import tempfile
import json

# Add parent directory to path so we can import the module
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from ipfs_datasets_py.jsonnet_utils import (
    JsonnetConverter,
    jsonnet_to_json,
    jsonnet_to_jsonl,
    jsonl_to_jsonnet,
    jsonnet_to_parquet,
)

from ipfs_datasets_py.car_conversion import DataInterchangeUtils
from ipfs_datasets_py.dataset_serialization import DatasetSerializer


def create_sample_jsonnet(file_path):
    """Create a sample Jsonnet file for testing."""
    # Jsonnet template with variables and functions
    jsonnet_template = """
// Sample Jsonnet template demonstrating various features
local users = [
  { name: "Alice", age: 30, role: "engineer" },
  { name: "Bob", age: 25, role: "designer" },
  { name: "Charlie", age: 35, role: "manager" },
];

local department = std.extVar("department");
local multiplier = std.parseJson(std.extVar("multiplier"));

// Generate records with computed fields
[
  user + {
    id: i,
    department: department,
    salary: (user.age * 1000) * multiplier,
    is_senior: user.age >= 30,
  }
  for i in std.range(0, std.length(users) - 1)
  for user in [users[i]]
]
"""
    
    with open(file_path, 'w') as f:
        f.write(jsonnet_template)
    
    return file_path


def example_jsonnet_to_json():
    """Example of converting Jsonnet to JSON."""
    print("\n=== Example: Jsonnet to JSON ===")
    
    # Simple Jsonnet template
    jsonnet_str = """
{
  name: "Example",
  items: [
    { id: 1, value: "first" },
    { id: 2, value: "second" },
    { id: 3, value: "third" },
  ],
  timestamp: "2024-01-01T00:00:00Z",
}
"""
    
    # Convert to JSON
    json_str = jsonnet_to_json(jsonnet_str)
    print("Evaluated JSON:")
    print(json_str)
    
    # Parse to verify
    data = json.loads(json_str)
    print(f"\nParsed data has {len(data['items'])} items")


def example_jsonnet_with_variables():
    """Example of using Jsonnet with external variables."""
    print("\n=== Example: Jsonnet with External Variables ===")
    
    with tempfile.TemporaryDirectory() as temp_dir:
        # Create sample Jsonnet file
        jsonnet_path = os.path.join(temp_dir, "sample.jsonnet")
        create_sample_jsonnet(jsonnet_path)
        print(f"Created sample Jsonnet file at {jsonnet_path}")
        
        # Evaluate with external variables
        converter = JsonnetConverter()
        json_str = converter.jsonnet_file_to_json(
            jsonnet_path,
            ext_vars={
                "department": "Engineering",
                "multiplier": "1.5"
            }
        )
        
        print("\nEvaluated JSON:")
        data = json.loads(json_str)
        print(json.dumps(data, indent=2))


def example_jsonnet_to_jsonl():
    """Example of converting Jsonnet to JSONL."""
    print("\n=== Example: Jsonnet to JSONL ===")
    
    with tempfile.TemporaryDirectory() as temp_dir:
        # Create sample Jsonnet file
        jsonnet_path = os.path.join(temp_dir, "sample.jsonnet")
        create_sample_jsonnet(jsonnet_path)
        
        # Convert to JSONL using the file function
        converter = JsonnetConverter()
        jsonl_path = os.path.join(temp_dir, "output.jsonl")
        output_path = converter.jsonnet_file_to_jsonl(
            jsonnet_path,
            jsonl_path,
            ext_vars={
                "department": "Engineering",
                "multiplier": "2.0"
            }
        )
        
        print(f"Converted to JSONL: {output_path}")
        
        # Read and display
        with open(output_path, 'r') as f:
            lines = f.readlines()
            print(f"JSONL file has {len(lines)} lines")
            print("\nFirst line:")
            print(json.dumps(json.loads(lines[0]), indent=2))


def example_jsonl_to_jsonnet():
    """Example of converting JSONL to Jsonnet."""
    print("\n=== Example: JSONL to Jsonnet ===")
    
    with tempfile.TemporaryDirectory() as temp_dir:
        # Create sample JSONL file
        jsonl_path = os.path.join(temp_dir, "sample.jsonl")
        sample_data = [
            {"id": 1, "name": "Item 1", "value": 100},
            {"id": 2, "name": "Item 2", "value": 200},
            {"id": 3, "name": "Item 3", "value": 300},
        ]
        
        with open(jsonl_path, 'w') as f:
            for record in sample_data:
                f.write(json.dumps(record) + '\n')
        
        print(f"Created sample JSONL file with {len(sample_data)} records")
        
        # Convert to Jsonnet
        jsonnet_path = os.path.join(temp_dir, "output.jsonnet")
        output_path = jsonl_to_jsonnet(jsonl_path, jsonnet_path)
        
        print(f"Converted to Jsonnet: {output_path}")
        
        # Read and display
        with open(output_path, 'r') as f:
            content = f.read()
            print("\nJsonnet content (first 200 chars):")
            print(content[:200] + "..." if len(content) > 200 else content)


def example_jsonnet_to_parquet():
    """Example of converting Jsonnet to Parquet."""
    print("\n=== Example: Jsonnet to Parquet ===")
    
    try:
        import pyarrow.parquet as pq
        
        with tempfile.TemporaryDirectory() as temp_dir:
            # Create sample Jsonnet file
            jsonnet_path = os.path.join(temp_dir, "sample.jsonnet")
            create_sample_jsonnet(jsonnet_path)
            
            # Convert to Parquet using the file function
            converter = JsonnetConverter()
            parquet_path = os.path.join(temp_dir, "output.parquet")
            output_path = converter.jsonnet_file_to_parquet(
                jsonnet_path,
                parquet_path,
                ext_vars={
                    "department": "Engineering",
                    "multiplier": "1.8"
                },
                compression="snappy"
            )
            
            print(f"Converted to Parquet: {output_path}")
            
            # Read and display statistics
            table = pq.read_table(output_path)
            print(f"Row count: {table.num_rows}")
            print(f"Column count: {len(table.column_names)}")
            print(f"Columns: {', '.join(table.column_names)}")
            print(f"File size: {os.path.getsize(output_path) / 1024:.2f} KB")
            
            # Display first few rows
            print("\nFirst 2 rows:")
            df = table.to_pandas().head(2)
            print(df)
            
    except ImportError:
        print("PyArrow not available, skipping Parquet example")


def example_jsonnet_to_car():
    """Example of converting Jsonnet to CAR (Content Archive)."""
    print("\n=== Example: Jsonnet to CAR ===")
    
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            # Create sample Jsonnet file
            jsonnet_path = os.path.join(temp_dir, "sample.jsonnet")
            create_sample_jsonnet(jsonnet_path)
            
            # Convert to CAR
            car_path = os.path.join(temp_dir, "output.car")
            converter = DataInterchangeUtils()
            root_cid = converter.jsonnet_to_car(
                jsonnet_path,
                car_path,
                ext_vars={
                    "department": "Engineering",
                    "multiplier": "2.5"
                }
            )
            
            print(f"Converted to CAR: {car_path}")
            print(f"Root CID: {root_cid}")
            print(f"File size: {os.path.getsize(car_path) / 1024:.2f} KB")
            
            # Convert back to Jsonnet
            output_jsonnet_path = os.path.join(temp_dir, "recovered.jsonnet")
            recovered_path = converter.car_to_jsonnet(car_path, output_jsonnet_path)
            
            print(f"\nConverted back to Jsonnet: {recovered_path}")
            
            # Verify content
            with open(recovered_path, 'r') as f:
                content = f.read()
                data = json.loads(content)
                print(f"Recovered {len(data)} records")
                
    except ImportError as e:
        print(f"Required libraries not available: {e}")
        print("Skipping CAR example")


def example_jsonnet_ipld_storage():
    """Example of storing Jsonnet data in IPLD."""
    print("\n=== Example: Jsonnet to IPLD Storage ===")
    
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            # Create sample Jsonnet file
            jsonnet_path = os.path.join(temp_dir, "sample.jsonnet")
            create_sample_jsonnet(jsonnet_path)
            
            # Serialize to IPLD
            serializer = DatasetSerializer()
            cid = serializer.serialize_jsonnet(
                jsonnet_path,
                ext_vars={
                    "department": "Engineering",
                    "multiplier": "2.2"
                }
            )
            
            print(f"Serialized to IPLD with CID: {cid}")
            
            # Deserialize from IPLD
            output_jsonnet_path = os.path.join(temp_dir, "recovered.jsonnet")
            recovered_path = serializer.deserialize_jsonnet(cid, output_jsonnet_path)
            
            print(f"Deserialized to: {recovered_path}")
            
            # Verify content
            with open(recovered_path, 'r') as f:
                content = f.read()
                data = json.loads(content)
                print(f"Recovered data with {len(data)} records")
                
    except ImportError as e:
        print(f"Required libraries not available: {e}")
        print("Skipping IPLD example")


def main():
    """Run all examples."""
    print("Jsonnet Conversion Examples")
    print("=" * 50)
    
    # Check if jsonnet is available
    try:
        import _jsonnet
        has_jsonnet = True
    except ImportError:
        print("\nWarning: jsonnet library not available!")
        print("Install it with: pip install jsonnet")
        print("\nSome examples will be skipped.\n")
        has_jsonnet = False
    
    if has_jsonnet:
        # Run examples
        example_jsonnet_to_json()
        example_jsonnet_with_variables()
        example_jsonnet_to_jsonl()
        example_jsonl_to_jsonnet()
        example_jsonnet_to_parquet()
        example_jsonnet_to_car()
        example_jsonnet_ipld_storage()
        
        print("\n" + "=" * 50)
        print("All examples completed successfully!")
    else:
        print("Please install jsonnet to run the examples.")


if __name__ == "__main__":
    main()
