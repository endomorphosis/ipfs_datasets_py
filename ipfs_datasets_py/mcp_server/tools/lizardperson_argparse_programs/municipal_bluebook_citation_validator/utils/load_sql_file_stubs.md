# Function and Class stubs from '/home/kylerose1946/ipfs_datasets_py/ipfs_datasets_py/mcp_server/tools/lizardperson_argparse_programs/municipal_bluebook_citation_validator/utils/load_sql_file.py'

Files last updated: 1751408933.7364564

Stub file last updated: 2025-07-07 01:10:14

## load_sql_file

```python
def load_sql_file(path: str | Path, encoding = "utf-8") -> str:
    """
    Load and return the contents of a SQL file as a string.

Args:
    path (str or Path): Path to the SQL file.
    encoding (str): Encoding to use when reading the file. Defaults to "utf-8".

Returns:
    str: Contents of the SQL file.

Raises:
    TypeError: If the provided path is not a string or Path object.
    ValueError: If the path does not point to a SQL file.
    FileNotFoundError: If the SQL file does not exist or cannot be found.
    IOError: If there is an error reading the file.
    Exception: For any other unexpected errors.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A
