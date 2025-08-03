# Function and Class stubs from '/home/kylerose1946/ipfs_datasets_py/ipfs_datasets_py/jsonl_to_parquet.py'

Files last updated: 1751419179.8831594

Stub file last updated: 2025-07-07 02:11:02

## batch_jsonl_to_parquet

```python
def batch_jsonl_to_parquet(jsonl_dir: str, parquet_dir: str, file_pattern: str = "*.jsonl", recursive: bool = False, **kwargs) -> List[str]:
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
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## fix_problematic_columns

```python
def fix_problematic_columns(df):
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## infer_schema_from_jsonl

```python
def infer_schema_from_jsonl(jsonl_path: str, sample_size: int = 1000) -> pa.Schema:
    """
    Infer Arrow schema from a JSONL file.

Args:
    jsonl_path: Path to the JSONL file
    sample_size: Number of records to sample for schema inference

Returns:
    pyarrow.Schema: The inferred schema
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## jsonl_to_arrow

```python
def jsonl_to_arrow(jsonl_path: str, schema: Optional[pa.Schema] = None, force_string_columns: List[str] = None, all_strings: bool = False) -> pa.Table:
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
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## jsonl_to_parquet

```python
def jsonl_to_parquet(jsonl_path: str, parquet_path: str, schema: Optional[pa.Schema] = None, compression: str = "snappy", row_group_size: int = 100000, force_string_columns: List[str] = None, all_strings: bool = False) -> str:
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
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## main

```python
def main():
    """
    Command-line interface for converting JSONL files to Parquet format.

This function provides a comprehensive CLI for converting JSON Lines files to
Apache Parquet format with advanced type handling and batch processing capabilities.

Features:
    - Single file or batch directory processing
    - Recursive directory traversal with file pattern matching
    - Configurable compression codecs (snappy, gzip, brotli, etc.)
    - Advanced type preservation and string column enforcement
    - Customizable row group sizes for optimal performance
    - Verbose logging and debug modes
    
Command-line Arguments:
    input: Path to input JSONL file or directory
    output: Path to output Parquet file or directory
    --batch, -b: Enable batch processing for multiple files
    --pattern, -p: File pattern for batch mode (default: "*.jsonl")
    --recursive, -r: Recursively process subdirectories
    --compression, -c: Compression codec (default: "snappy")
    --row-group-size, -g: Number of rows per group (default: 100000)
    --verbose, -v: Enable verbose logging
    --all-strings, -s: Force all columns to string type
    --string-columns: Comma-separated list of columns to force as strings
    --debug, -d: Enable debug mode with detailed error traces
    --preserve-types: Prevent automatic string-to-boolean conversion
    
Type Handling:
    The function provides sophisticated type handling to address common issues
    with automatic type inference, particularly for string values that might
    be misinterpreted as booleans (e.g., "true", "false", "yes", "no", "auto").
    
Returns:
    int: Exit code (0 for success, 1 for error)
    
Raises:
    SystemExit: On argument parsing errors or when return code is non-zero
    
Examples:
    Convert single file:
        python script.py input.jsonl output.parquet
        
    Batch convert with compression:
        python script.py -b -c gzip input_dir/ output_dir/
        
    Preserve string types for specific columns:
        python script.py --string-columns "id,name,status" input.jsonl output.parquet
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## safe_to_arrow_table

```python
def safe_to_arrow_table(df, schema = None):
```
* **Async:** False
* **Method:** False
* **Class:** N/A
