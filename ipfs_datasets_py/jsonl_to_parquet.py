"""
Utility for converting JSONL files to Parquet format.

This module provides a simple interface for converting JSON Lines files to Parquet format,
using the IPFS Datasets library's conversion utilities.
"""

import os
import sys
import json
import logging
import argparse
from typing import List, Dict, Any, Optional, Union, TextIO
import pyarrow as pa
import pyarrow.parquet as pq

def jsonl_to_arrow(jsonl_path: str, schema: Optional[pa.Schema] = None,
                 force_string_columns: List[str] = None, all_strings: bool = False) -> pa.Table:
    """
    Convert a JSONL file to an Arrow table.

    Args:
        jsonl_path: Path to the JSONL file
        schema: Optional Arrow schema to use (inferred if not provided)
        force_string_columns: List of column names to force as strings
        all_strings: Whether to force all columns to strings

    Returns:
        pyarrow.Table: The converted data as an Arrow table
    """
    import pandas as pd
    from pandas.api.types import is_string_dtype

    force_string_columns = force_string_columns or []

    # Helper function to fix problematic value columns before conversion
    def fix_problematic_columns(df):
        # Get columns that might have boolean-like strings
        potentially_problematic = []

        for col in df.columns:
            # Skip columns that are already properly typed
            if not is_string_dtype(df[col].dtype) and not all_strings and col not in force_string_columns:
                continue

            # Check sample values
            sample_values = df[col].dropna().head(100).astype(str)
            has_boolean_strings = any(val.lower() in ('true', 'false', 'yes', 'no', 'auto', 'null', 'none')
                                   for val in sample_values if isinstance(val, str))

            if has_boolean_strings:
                potentially_problematic.append(col)
                logging.warning(f"Column '{col}' contains boolean-like strings (e.g. 'auto', 'true'). "
                               f"Converting to object type to prevent misinterpretation.")

        # Fix all identified problematic columns
        for col in potentially_problematic:
            # Explicitly keep the strings as strings by using object dtype
            df[col] = df[col].astype(object)

        # Force any explicitly requested columns to string
        for col in force_string_columns:
            if col in df.columns:
                df[col] = df[col].astype(object)

        # Force all columns to string if requested
        if all_strings:
            for col in df.columns:
                df[col] = df[col].astype(object)

        return df

    # Helper function to safely convert to Arrow table with better error handling
    def safe_to_arrow_table(df, schema=None):
        # Fix problematic columns before conversion
        df = fix_problematic_columns(df)

        try:
            if schema:
                # Convert to records and then to pyarrow table
                records = df.to_dict('records')
                return pa.Table.from_pylist(records, schema=schema)
            else:
                # Directly convert from pandas with careful type handling
                return pa.Table.from_pandas(df, preserve_index=False)
        except pa.ArrowInvalid as e:
            # Provide more helpful error message
            error_str = str(e)
            logging.error(f"Arrow conversion error: {error_str}")

            if "Could not convert" in error_str and "boolean" in error_str:
                problematic_col = None

                # Try to find the problematic column
                for col in df.columns:
                    if col in error_str:
                        problematic_col = col
                        break

                # Handle the problematic column
                if problematic_col:
                    logging.warning(f"Conversion issue detected with column '{problematic_col}'. "
                                   f"Converting all values to strings.")
                    # Replace the actual problematic values
                    df[problematic_col] = df[problematic_col].astype(str)
                else:
                    # If we can't identify the column, convert all string columns
                    logging.warning("Converting all string columns to object type to prevent type inference issues.")
                    for col in df.columns:
                        if is_string_dtype(df[col].dtype):
                            df[col] = df[col].astype(str)

                # Try again with fixed columns
                if schema:
                    schema_dict = {field.name: field.type for field in schema}
                    # Adjust schema if needed for problematic column
                    if problematic_col and problematic_col in schema_dict:
                        schema_dict[problematic_col] = pa.string()
                        schema = pa.schema([(name, type) for name, type in schema_dict.items()])

                    records = df.to_dict('records')
                    return pa.Table.from_pylist(records, schema=schema)
                else:
                    return pa.Table.from_pandas(df, preserve_index=False)
            else:
                # For other conversion issues, try with more aggressive type control
                logging.warning("Attempting conversion with more aggressive type control...")

                # Convert all columns to strings as a last resort
                for col in df.columns:
                    df[col] = df[col].astype(str)

                # Try one more time with string conversion
                if schema:
                    records = df.to_dict('records')
                    return pa.Table.from_pylist(records, schema=pa.schema([
                        (field.name, pa.string() if field.name in df.columns else field.type)
                        for field in schema
                    ]))
                else:
                    return pa.Table.from_pandas(df, preserve_index=False)

    # Read JSONL directly into pandas with more explicit type handling
    try:
        # Try to use pandas' built-in JSONL reader
        df = pd.read_json(jsonl_path, lines=True, dtype_backend='pyarrow')

        # Pre-emptively convert problematic columns to strings
        for col in df.columns:
            # Check if column has any values that might be misinterpreted
            sample_values = df[col].dropna().head(1000).astype(str)
            if any(val.lower() in ('true', 'false', 'yes', 'no', 'auto', 'null', 'none')
                  for val in sample_values if isinstance(val, str)):
                logging.info(f"Converting column '{col}' to string type to prevent misinterpretation")
                # Use object dtype instead of str to better preserve original values
                df[col] = df[col].astype('object')

        # Use our helper function to safely convert to Arrow table
        return safe_to_arrow_table(df, schema)

    except (ValueError, pa.ArrowInvalid, pd.errors.ParserError) as e:
        logging.warning(f"Pandas JSON reader failed: {str(e)}. Falling back to manual parsing.")

        # Manual parsing as fallback
        records = []
        with open(jsonl_path, 'r') as f:
            for i, line in enumerate(f):
                line = line.strip()
                if line:  # Skip empty lines
                    try:
                        record = json.loads(line)
                        records.append(record)
                    except json.JSONDecodeError as e:
                        logging.warning(f"Error parsing JSON line {i}: {str(e)}")

        if not records:
            raise ValueError(f"No valid JSON records found in {jsonl_path}")

        # Create a DataFrame with explicit string conversion for ambiguous values
        df = pd.DataFrame(records)

        # Process each column to prevent type inference issues
        for col in df.columns:
            if df[col].apply(lambda x: isinstance(x, str) and x.lower() in
                          ('true', 'false', 'yes', 'no', 'auto', 'null', 'none')).any():
                logging.info(f"Converting column '{col}' to string type to prevent misinterpretation")
                # Use object dtype instead of str to better preserve original values
                df[col] = df[col].astype('object')

        # Use our helper function to safely convert to Arrow table
        return safe_to_arrow_table(df, schema)

def jsonl_to_parquet(jsonl_path: str, parquet_path: str,
                   schema: Optional[pa.Schema] = None,
                   compression: str = 'snappy',
                   row_group_size: int = 100000,
                   force_string_columns: List[str] = None,
                   all_strings: bool = False) -> str:
    """
    Convert a JSONL file to Parquet format.

    Args:
        jsonl_path: Path to the JSONL file
        parquet_path: Path to save the Parquet file
        schema: Optional Arrow schema to use (inferred if not provided)
        compression: Compression codec to use ('snappy', 'gzip', 'brotli', etc.)
        row_group_size: Number of rows per row group
        force_string_columns: List of column names to force as strings
        all_strings: Whether to force all columns to strings

    Returns:
        str: Path to the created Parquet file
    """
    # Convert to Arrow
    table = jsonl_to_arrow(
        jsonl_path,
        schema=schema,
        force_string_columns=force_string_columns,
        all_strings=all_strings
    )

    # Write to Parquet
    pq.write_table(
        table,
        parquet_path,
        compression=compression,
        row_group_size=row_group_size
    )

    return parquet_path

def batch_jsonl_to_parquet(jsonl_dir: str, parquet_dir: str,
                        file_pattern: str = "*.jsonl",
                        recursive: bool = False,
                        **kwargs) -> List[str]:
    """
    Convert multiple JSONL files to Parquet format.

    Args:
        jsonl_dir: Directory containing JSONL files
        parquet_dir: Directory to save Parquet files
        file_pattern: Pattern to match JSONL files
        recursive: Whether to search subdirectories
        **kwargs: Additional arguments to pass to jsonl_to_parquet

    Returns:
        List[str]: Paths to the created Parquet files
    """
    import glob

    # Create output directory if it doesn't exist
    os.makedirs(parquet_dir, exist_ok=True)

    # Find JSONL files
    if recursive:
        pattern = os.path.join(jsonl_dir, "**", file_pattern)
        files = glob.glob(pattern, recursive=True)
    else:
        pattern = os.path.join(jsonl_dir, file_pattern)
        files = glob.glob(pattern)

    if not files:
        raise ValueError(f"No files matching {pattern} found")

    # Convert each file
    output_paths = []
    for jsonl_file in files:
        # Determine output path
        rel_path = os.path.relpath(jsonl_file, jsonl_dir)
        output_path = os.path.join(parquet_dir, rel_path.replace('.jsonl', '.parquet'))

        # Create directory if needed
        os.makedirs(os.path.dirname(output_path), exist_ok=True)

        # Convert file
        try:
            output_path = jsonl_to_parquet(jsonl_file, output_path, **kwargs)
            output_paths.append(output_path)
            logging.info(f"Converted {jsonl_file} to {output_path}")
        except Exception as e:
            logging.error(f"Error converting {jsonl_file}: {str(e)}")

    return output_paths

def infer_schema_from_jsonl(jsonl_path: str, sample_size: int = 1000) -> pa.Schema:
    """
    Infer Arrow schema from a JSONL file.

    Args:
        jsonl_path: Path to the JSONL file
        sample_size: Number of records to sample for schema inference

    Returns:
        pyarrow.Schema: The inferred schema
    """
    # Read sample records
    records = []
    with open(jsonl_path, 'r') as f:
        for i, line in enumerate(f):
            if i >= sample_size:
                break

            line = line.strip()
            if line:  # Skip empty lines
                try:
                    record = json.loads(line)
                    records.append(record)
                except json.JSONDecodeError:
                    continue

    if not records:
        raise ValueError(f"No valid JSON records found in {jsonl_path}")

    # Create schema from records
    table = pa.Table.from_pylist(records)
    return table.schema

def main():
    """Command-line interface for JSONL to Parquet conversion."""
    parser = argparse.ArgumentParser(description="Convert JSONL files to Parquet format")

    parser.add_argument('input', help="Input JSONL file or directory")
    parser.add_argument('output', help="Output Parquet file or directory")
    parser.add_argument('--batch', '-b', action='store_true', help="Process multiple files")
    parser.add_argument('--pattern', '-p', default="*.jsonl", help="File pattern for batch mode")
    parser.add_argument('--recursive', '-r', action='store_true', help="Recursively process subdirectories")
    parser.add_argument('--compression', '-c', default='snappy', help="Compression codec (snappy, gzip, brotli, etc.)")
    parser.add_argument('--row-group-size', '-g', type=int, default=100000, help="Row group size")
    parser.add_argument('--verbose', '-v', action='store_true', help="Enable verbose logging")
    parser.add_argument('--all-strings', '-s', action='store_true', help="Convert all string values to string type to avoid inference issues")
    parser.add_argument('--string-columns', type=str, help="Comma-separated list of column names to force as string type")
    parser.add_argument('--debug', '-d', action='store_true', help="Enable debug mode with detailed error information")
    parser.add_argument('--preserve-types', action='store_true', help="Preserve original types as much as possible, preventing auto-conversion of strings to boolean")

    args = parser.parse_args()

    # Configure logging
    log_level = logging.DEBUG if args.debug else (logging.INFO if args.verbose else logging.WARNING)
    logging.basicConfig(level=log_level, format='%(asctime)s - %(levelname)s - %(message)s')

    # Process string columns if provided
    string_columns = None
    if args.string_columns:
        string_columns = [col.strip() for col in args.string_columns.split(',')]
        logging.info(f"Forcing columns to string type: {string_columns}")

    try:
        # Create a custom schema if specific column types are requested
        schema = None
        if args.all_strings or string_columns or args.preserve_types:
            # First read a sample to determine schema
            logging.info("Creating custom schema with type enforcement...")

            # Sample the input file to infer base schema
            with open(args.input, 'r') as f:
                sample_records = []
                for i, line in enumerate(f):
                    if i >= 100:  # Sample first 100 records
                        break
                    try:
                        sample_records.append(json.loads(line.strip()))
                    except json.JSONDecodeError:
                        continue

            if not sample_records:
                raise ValueError(f"Could not read any valid JSON records from {args.input}")

            # Create pandas DataFrame for schema inference
            import pandas as pd
            sample_df = pd.DataFrame(sample_records)

            # Handle type preservation and conversions
            if args.preserve_types:
                # Detect and convert any columns with values that might cause type inference issues
                for col in sample_df.columns:
                    sample_values = sample_df[col].dropna().head(100).astype(str)
                    if any(val.lower() in ('true', 'false', 'yes', 'no', 'auto', 'null', 'none')
                           for val in sample_values if isinstance(val, str)):
                        sample_df[col] = sample_df[col].astype('object')
                        logging.info(f"Preserving column '{col}' as object type to prevent misinterpretation")
            elif args.all_strings:
                # Force all columns to string type
                for col in sample_df.columns:
                    sample_df[col] = sample_df[col].astype('object')
                logging.info("Converted all columns to object type")
            elif string_columns:
                # Force specific columns to string type
                for col in string_columns:
                    if col in sample_df.columns:
                        sample_df[col] = sample_df[col].astype('object')
                        logging.info(f"Converted column '{col}' to object type")

            # Create Arrow table from DataFrame with enforced types
            try:
                sample_table = pa.Table.from_pandas(sample_df, preserve_index=False)
                schema = sample_table.schema
                logging.info(f"Created schema with {len(schema.names)} columns")
            except pa.ArrowInvalid as e:
                logging.warning(f"Error creating schema: {str(e)}. Using default schema instead.")
                # This fallback ensures we don't fail if schema creation has issues

        # Prepare parameters
        kwargs = {
            'compression': args.compression,
            'row_group_size': args.row_group_size,
            'schema': schema,
            'all_strings': args.all_strings,
            'force_string_columns': string_columns if string_columns else None
        }

        # For type preservation, we want to force certain known columns
        if args.preserve_types:
            # Special handling for common problematic columns
            problematic_columns = []
            # Try to read first few lines to identify problematic columns
            try:
                with open(args.input, 'r') as f:
                    for i, line in enumerate(f):
                        if i >= 5:  # Just check first 5 lines
                            break
                        try:
                            data = json.loads(line.strip())
                            # Identify potential problematic columns
                            for key, value in data.items():
                                if isinstance(value, str) and value.lower() in ('true', 'false', 'yes', 'no', 'auto', 'null', 'none'):
                                    problematic_columns.append(key)
                        except:
                            pass

                # Remove duplicates
                problematic_columns = list(set(problematic_columns))
                if problematic_columns:
                    logging.info(f"Identified potentially problematic columns with boolean-like strings: {problematic_columns}")

                    # Add to force_string_columns
                    force_string_cols = kwargs.get('force_string_columns', []) or []
                    if force_string_cols:
                        force_string_cols.extend(problematic_columns)
                    else:
                        kwargs['force_string_columns'] = problematic_columns
            except Exception as e:
                logging.warning(f"Error scanning for problematic columns: {str(e)}")

        if args.batch:
            # Batch conversion
            output_paths = batch_jsonl_to_parquet(
                args.input,
                args.output,
                file_pattern=args.pattern,
                recursive=args.recursive,
                **kwargs
            )
            print(f"Converted {len(output_paths)} files to Parquet format")
            for path in output_paths:
                print(f"  {path}")
        else:
            # Single file conversion
            output_path = jsonl_to_parquet(
                args.input,
                args.output,
                **kwargs
            )
            print(f"Converted {args.input} to {output_path}")

            # Print basic statistics
            table = pq.read_table(output_path)
            print(f"Row count: {table.num_rows}")
            print(f"Column count: {len(table.column_names)}")
            print(f"Columns: {', '.join(table.column_names)}")
            print(f"File size: {os.path.getsize(output_path) / (1024*1024):.2f} MB")

    except Exception as e:
        if args.debug:
            import traceback
            logging.error(f"Error: {str(e)}")
            logging.error(traceback.format_exc())
        else:
            logging.error(f"Error: {str(e)}")
        return 1

    return 0

if __name__ == "__main__":
    sys.exit(main())
