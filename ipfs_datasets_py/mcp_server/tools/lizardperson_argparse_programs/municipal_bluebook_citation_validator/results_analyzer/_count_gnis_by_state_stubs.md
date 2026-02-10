# Function and Class stubs from '<repo-root>/ipfs_datasets_py/ipfs_datasets_py/mcp_server/tools/lizardperson_argparse_programs/municipal_bluebook_citation_validator/stratified_sampler/_count_gnis_by_state.py'

Files last updated: 1751408933.7364564

Stub file last updated: 2025-07-07 01:10:14

## count_gnis_by_state

```python
def count_gnis_by_state(citations: list[Path], reference_db) -> dict[str, int]:
    """
    Count how many GNIS exist in each state from filenames.

Args:
    citations (list[Path]): list of citation parquet files.
    reference_db (DatabaseConnection): Database connection to MySQL, reference database.
    mysql_configs (dict[str, Any]): MySQL connection settings.

Returns:
    dict[str, int]: dictionary mapping state names to jurisdiction counts.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A
