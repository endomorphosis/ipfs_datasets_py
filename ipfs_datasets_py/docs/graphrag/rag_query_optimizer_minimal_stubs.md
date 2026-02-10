# Function and Class stubs from '<repo-root>/ipfs_datasets_py/ipfs_datasets_py/optimizers/graphrag/query_optimizer_minimal.py'

Files last updated: 1748635923.4613795

Stub file last updated: 2025-07-07 01:59:52

## GraphRAGQueryOptimizer

```python
class GraphRAGQueryOptimizer:
    """
    Optimizer for GraphRAG queries based on statistical learning.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## GraphRAGQueryStats

```python
class GraphRAGQueryStats:
    """
    Statistics collector for GraphRAG queries.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## __init__

```python
def __init__(self):
    """
    Initialize the statistics collector.
    """
```
* **Async:** False
* **Method:** True
* **Class:** GraphRAGQueryStats

## __init__

```python
def __init__(self):
    """
    Initialize the optimizer.
    """
```
* **Async:** False
* **Method:** True
* **Class:** GraphRAGQueryOptimizer

## _create_fallback_plan

```python
def _create_fallback_plan(self, query: Dict[str, Any], priority: str = "normal", error: Optional[str] = None) -> Dict[str, Any]:
    """
    Create a fallback query plan when optimization fails.
    """
```
* **Async:** False
* **Method:** True
* **Class:** GraphRAGQueryOptimizer

## _derive_rules_from_patterns

```python
def _derive_rules_from_patterns(self, successful_queries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Derive optimization rules from successful query patterns.
    """
```
* **Async:** False
* **Method:** True
* **Class:** GraphRAGQueryOptimizer

## _derive_wikipedia_specific_rules

```python
def _derive_wikipedia_specific_rules(self, successful_queries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Derives Wikipedia-specific optimization rules from successful query patterns.

Args:
    successful_queries: List of successful query metrics

Returns:
    List: Wikipedia-specific optimization rules
    """
```
* **Async:** False
* **Method:** True
* **Class:** GraphRAGQueryOptimizer

## enable_learning

```python
def enable_learning(self, enabled: bool = True) -> None:
    """
    Enable or disable statistical learning.
    """
```
* **Async:** False
* **Method:** True
* **Class:** GraphRAGQueryOptimizer

## optimize_query

```python
def optimize_query(self, query: Dict[str, Any], priority: str = "normal") -> Dict[str, Any]:
    """
    Optimize a query based on historical patterns.
    """
```
* **Async:** False
* **Method:** True
* **Class:** GraphRAGQueryOptimizer

## record_query

```python
def record_query(self, query_id: str, params: Dict[str, Any], results: List[Dict], duration: float, success: bool = True) -> None:
    """
    Record a query and its results.
    """
```
* **Async:** False
* **Method:** True
* **Class:** GraphRAGQueryStats
