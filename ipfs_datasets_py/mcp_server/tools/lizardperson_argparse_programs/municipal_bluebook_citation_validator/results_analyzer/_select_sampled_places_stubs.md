# Function and Class stubs from '<repo-root>/ipfs_datasets_py/ipfs_datasets_py/mcp_server/tools/lizardperson_argparse_programs/municipal_bluebook_citation_validator/stratified_sampler/_select_sampled_places.py'

Files last updated: 1751408933.7364564

Stub file last updated: 2025-07-07 01:10:14

## select_sampled_places

```python
def select_sampled_places(citations: list[Path], sample_strategy: dict[str, int], reference_db) -> list[int]:
    """
    Randomly select specific places to validate based on sampling strategy.

Args:
    citations (list[Path]): list of citation parquet files.
    sample_strategy (dict[str, int]): Dictionary mapping state names to sample sizes.
    reference_db (DatabaseConnection): Database connection to MySQL, reference database.

Returns:
    list[int]: list of sampled place GNIS identifiers.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A
