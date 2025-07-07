# Function and Class stubs from '/home/kylerose1946/ipfs_datasets_py/ipfs_datasets_py/enhanced_rag_visualization.py'

Files last updated: 1748635923.4313796

Stub file last updated: 2025-07-07 02:11:01

## EnhancedQueryAuditVisualizer

```python
class EnhancedQueryAuditVisualizer(EnhancedQueryVisualizer):
    """
    Extended visualization capabilities for RAG query metrics with audit integration.

This class adds audit-related visualizations to the EnhancedQueryVisualizer,
including correlation analysis between query performance and security events.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## analyze_query_audit_correlation

```python
def analyze_query_audit_correlation(self, audit_metrics_aggregator, time_window: Optional[int] = None, title: str = "Query-Audit Correlation Analysis", show_plot: bool = True, output_file: Optional[str] = None, interactive: bool = False, figsize: Tuple[int, int] = (14, 10)) -> Optional[Union[Figure, Dict[str, Any], Dict[str, float]]]:
    """
    Analyze correlation between RAG query performance and audit events.

This method identifies patterns and correlations between security events
and query performance degradation, helping to detect security-related
performance impacts.

Args:
    audit_metrics_aggregator: AuditMetricsAggregator to get audit events from
    time_window: Time window in seconds to include, or None for all time
    title: Plot title
    show_plot: Whether to display the plot
    output_file: Path to save the plot image
    interactive: Whether to create an interactive plot (requires plotly)
    figsize: Figure size (width, height) in inches

Returns:
    matplotlib.figure.Figure, plotly figure dict, Dict of correlation stats, or None
    """
```
* **Async:** False
* **Method:** True
* **Class:** EnhancedQueryAuditVisualizer

## visualize_query_audit_metrics

```python
def visualize_query_audit_metrics(self, audit_metrics_aggregator, time_window: Optional[int] = None, title: str = "Query Performance and Audit Events Timeline", show_plot: bool = True, output_file: Optional[str] = None, interactive: bool = False, figsize: Tuple[int, int] = (14, 8)) -> Optional[Union[Figure, Dict[str, Any]]]:
    """
    Visualize the relationship between RAG query performance and audit/security events.

Args:
    audit_metrics_aggregator: AuditMetricsAggregator to get audit events from
    time_window: Time window in seconds to include, or None for all time
    title: Plot title
    show_plot: Whether to display the plot
    output_file: Path to save the plot image
    interactive: Whether to create an interactive plot (requires plotly)
    figsize: Figure size (width, height) in inches

Returns:
    matplotlib.figure.Figure, plotly figure dict, or None
    """
```
* **Async:** False
* **Method:** True
* **Class:** EnhancedQueryAuditVisualizer
