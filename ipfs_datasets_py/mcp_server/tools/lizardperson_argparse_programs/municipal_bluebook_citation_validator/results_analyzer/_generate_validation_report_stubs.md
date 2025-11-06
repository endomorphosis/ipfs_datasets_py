# Function and Class stubs from '/home/kylerose1946/ipfs_datasets_py/ipfs_datasets_py/mcp_server/tools/lizardperson_argparse_programs/municipal_bluebook_citation_validator/generate_reports/_generate_validation_report.py'

Files last updated: 1751408933.7264564

Stub file last updated: 2025-07-07 01:10:14

## generate_validation_report

```python
def generate_validation_report(error_summary: dict[str, int], accuracy_stats: dict[str, float], estimates: dict[str, float], error_report_db) -> Path:
    """
    Generate a comprehensive validation report for municipal bluebook citations.

Args:
    error_summary (dict[str, int]): Error type counts.
    accuracy_stats (dict[str, float]): Accuracy metrics.
    estimates (dict[str, float]): Projected statistics.
    error_report_db (DatabaseConnection): DB connection for saving the report.

Returns:
    Path: Path to the generated validation report file.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A
