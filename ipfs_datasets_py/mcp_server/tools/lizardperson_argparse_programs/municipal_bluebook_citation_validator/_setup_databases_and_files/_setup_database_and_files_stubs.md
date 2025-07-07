# Function and Class stubs from '/home/kylerose1946/ipfs_datasets_py/ipfs_datasets_py/mcp_server/tools/lizardperson_argparse_programs/municipal_bluebook_citation_validator/_setup_databases_and_files/_setup_database_and_files.py'

Files last updated: 1751408933.7064564

Stub file last updated: 2025-07-07 02:39:56

## SetupDatabaseAndFiles

```python
class SetupDatabaseAndFiles:
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## __init__

```python
def __init__(self, resources: dict[str, Callable] = None, configs: dict[str, Any] = None) -> None:
```
* **Async:** False
* **Method:** True
* **Class:** SetupDatabaseAndFiles

## _make_sql_tables_dict

```python
def _make_sql_tables_dict(self, sql_configs: dict[str, Any]) -> dict[str, str]:
    """
    Create sql statements.
    """
```
* **Async:** False
* **Method:** True
* **Class:** SetupDatabaseAndFiles

## get_all_files_in_directory

```python
def get_all_files_in_directory(directory: Path, pattern: str) -> list[Path]:
    """
    Get all files in a directory matching a specific pattern.
    """
```
* **Async:** False
* **Method:** True
* **Class:** SetupDatabaseAndFiles

## get_databases

```python
def get_databases(self) -> tuple['DatabaseConnection', 'DatabaseConnection']:
    """
    Set up and retrieve the error and reference databases for citation validation.

This method initializes both the error database and reference database by calling
their respective setup methods, then returns them as a tuple for use in citation
validation processes.

Returns:
    tuple[list]: A tuple containing two elements:
        - error_db (list): The error database containing validation error records
        - reference_db (list): The reference database containing citation reference data
    """
```
* **Async:** False
* **Method:** True
* **Class:** SetupDatabaseAndFiles

## get_files

```python
def get_files(self) -> tuple[list[Path], list[Path]]:
    """
    Retrieves lists of paths to citation and HTML parquet files from the citation and document directory.

Returns:
    tuple[list[Path], list[Path]]: A tuple containing:
        - First element: List of Path objects for citation parquet files (*_citation.parquet)
        - Second element: List of Path objects for HTML parquet files (*_html.parquet)
    """
```
* **Async:** False
* **Method:** True
* **Class:** SetupDatabaseAndFiles

## setup_error_database

```python
def setup_error_database(self, read_only: bool = False):
    """
    Connect to DuckDB database for storing validation errors.
    """
```
* **Async:** False
* **Method:** True
* **Class:** SetupDatabaseAndFiles

## setup_error_report_database

```python
def setup_error_report_database(self, read_only: bool = False):
    """
    Connect to DuckDB database for storing error reports.
    """
```
* **Async:** False
* **Method:** True
* **Class:** SetupDatabaseAndFiles

## setup_reference_database

```python
def setup_reference_database(self, read_only: bool = True) -> "DatabaseConnection":
    """
    Setup DuckDB with MySQL extension and establish connection.
    """
```
* **Async:** False
* **Method:** True
* **Class:** SetupDatabaseAndFiles
