"""
Example of using the JSONL to Parquet conversion utility.

This script demonstrates how to use the JSONL to Parquet conversion utility
for converting data between formats.
"""

import os
import sys
import json
import tempfile
import pyarrow.parquet as pq

# Add parent directory to path so we can import the module
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from ipfs_datasets_py.data_transformation.serialization.jsonl_to_parquet import (
    jsonl_to_parquet,
    batch_jsonl_to_parquet,
    infer_schema_from_jsonl,
    jsonl_to_arrow
)

def create_sample_jsonl(file_path, num_records=100):
    """Create a sample JSONL file for testing."""
    with open(file_path, 'w') as f:
        for i in range(num_records):
            record = {
                "id": i,
                "name": f"Record {i}",
                "value": i * 10.5,
                "tags": ["tag1", "tag2"] if i % 2 == 0 else ["tag3", "tag4"],
                "metadata": {
                    "created_at": "2023-10-26T12:34:56Z",
                    "source": "example",
                    "is_valid": True
                }
            }
            f.write(json.dumps(record) + '\n')

    return file_path

def example_single_file_conversion():
    """Example of converting a single JSONL file to Parquet."""
    print("\n=== Example: Single File Conversion ===")

    # Create a temporary directory for our example
    with tempfile.TemporaryDirectory() as temp_dir:
        # Create a sample JSONL file
        jsonl_path = os.path.join(temp_dir, "sample.jsonl")
        create_sample_jsonl(jsonl_path, num_records=1000)
        print(f"Created sample JSONL file with 1000 records at {jsonl_path}")

        # Convert to Parquet
        parquet_path = os.path.join(temp_dir, "sample.parquet")
        output_path = jsonl_to_parquet(jsonl_path, parquet_path, compression="snappy")
        print(f"Converted to Parquet: {output_path}")

        # Read and display statistics
        table = pq.read_table(output_path)
        print(f"Row count: {table.num_rows}")
        print(f"Column count: {len(table.column_names)}")
        print(f"Columns: {', '.join(table.column_names)}")
        print(f"File size: {os.path.getsize(output_path) / 1024:.2f} KB")

        # Display first few rows
        print("\nFirst 3 rows:")
        df = table.to_pandas().head(3)
        print(df)

def example_batch_conversion():
    """Example of batch converting multiple JSONL files to Parquet."""
    print("\n=== Example: Batch Conversion ===")

    # Create a temporary directory for our example
    with tempfile.TemporaryDirectory() as temp_dir:
        # Create input and output directories
        input_dir = os.path.join(temp_dir, "input")
        output_dir = os.path.join(temp_dir, "output")
        os.makedirs(input_dir, exist_ok=True)

        # Create sample JSONL files
        for i in range(3):
            jsonl_path = os.path.join(input_dir, f"file{i}.jsonl")
            create_sample_jsonl(jsonl_path, num_records=100)

        print(f"Created 3 sample JSONL files in {input_dir}")

        # Perform batch conversion
        output_paths = batch_jsonl_to_parquet(
            input_dir,
            output_dir,
            file_pattern="*.jsonl",
            compression="snappy"
        )

        print(f"Converted {len(output_paths)} files to Parquet format")
        for path in output_paths:
            table = pq.read_table(path)
            print(f"  {path}: {table.num_rows} rows, {len(table.column_names)} columns")

def example_schema_inference():
    """Example of inferring schema from a JSONL file."""
    print("\n=== Example: Schema Inference ===")

    # Create a temporary directory for our example
    with tempfile.TemporaryDirectory() as temp_dir:
        # Create a sample JSONL file
        jsonl_path = os.path.join(temp_dir, "sample.jsonl")
        create_sample_jsonl(jsonl_path, num_records=1000)

        # Infer schema
        schema = infer_schema_from_jsonl(jsonl_path, sample_size=100)
        print(f"Inferred schema from the first 100 records:")
        print(schema)

        # Use the inferred schema for conversion
        parquet_path = os.path.join(temp_dir, "sample_with_schema.parquet")
        output_path = jsonl_to_parquet(jsonl_path, parquet_path, schema=schema)

        print(f"Converted to Parquet using the inferred schema: {output_path}")
        print(f"File size: {os.path.getsize(output_path) / 1024:.2f} KB")

def example_arrow_integration():
    """Example of integration with Arrow for more complex processing."""
    print("\n=== Example: Arrow Integration ===")

    # Create a temporary directory for our example
    with tempfile.TemporaryDirectory() as temp_dir:
        # Create a sample JSONL file
        jsonl_path = os.path.join(temp_dir, "sample.jsonl")
        create_sample_jsonl(jsonl_path, num_records=1000)

        # Convert to Arrow
        table = jsonl_to_arrow(jsonl_path)
        print(f"Converted to Arrow table: {table.num_rows} rows, {len(table.column_names)} columns")

        # Perform Arrow transformations
        # Filter rows where id > 500
        filtered_table = table.filter(table['id'] > 500)
        print(f"Filtered table: {filtered_table.num_rows} rows")

        # Select specific columns
        selected_table = filtered_table.select(['id', 'name', 'value'])
        print(f"Selected columns: {selected_table.column_names}")

        # Sort by id (using pandas as Arrow doesn't have direct sort)
        import pandas as pd
        df = selected_table.to_pandas()
        df = df.sort_values('value', ascending=False)
        sorted_table = pa.Table.from_pandas(df)
        print(f"Sorted table (first 3 rows by highest value):")
        print(sorted_table.to_pandas().head(3))

        # Write processed data to Parquet
        output_path = os.path.join(temp_dir, "processed.parquet")
        pq.write_table(sorted_table, output_path)
        print(f"Wrote processed data to Parquet: {output_path}")
        print(f"File size: {os.path.getsize(output_path) / 1024:.2f} KB")

def main():
    """Run all examples."""
    print("JSONL to Parquet Conversion Examples")

    # Import pyarrow for Arrow examples
    try:
        import pyarrow as pa
        has_arrow = True
    except ImportError:
        print("Warning: pyarrow not available, skipping Arrow examples")
        has_arrow = False

    # Run examples
    example_single_file_conversion()
    example_batch_conversion()
    example_schema_inference()

    if has_arrow:
        example_arrow_integration()

    print("\nAll examples completed successfully!")

if __name__ == "__main__":
    main()
