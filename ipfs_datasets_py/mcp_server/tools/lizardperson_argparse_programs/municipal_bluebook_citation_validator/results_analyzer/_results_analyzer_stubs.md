# Function and Class stubs from '<repo-root>/ipfs_datasets_py/ipfs_datasets_py/mcp_server/tools/lizardperson_argparse_programs/municipal_bluebook_citation_validator/results_analyzer/_results_analyzer.py'

Files last updated: 1751408933.7264564

Stub file last updated: 2025-07-07 01:10:14

## ResultsAnalyzer

```python
class ResultsAnalyzer:
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## __init__

```python
def __init__(self, resources: dict[str, Callable] = None, configs: Configs = None) -> None:
```
* **Async:** False
* **Method:** True
* **Class:** ResultsAnalyzer

## analyze

```python
def analyze(self, error_db: DatabaseConnection, gnis_counts_by_state: dict[str, int], total_citations: int, total_errors: int) -> tuple[dict[str, Any], dict[str, float], dict[str, float]]:
```
* **Async:** False
* **Method:** True
* **Class:** ResultsAnalyzer
