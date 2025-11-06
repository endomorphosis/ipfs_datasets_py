# Function and Class stubs from '/home/kylerose1946/ipfs_datasets_py/ipfs_datasets_py/mcp_server/tools/audit_tools/generate_audit_report.py'

Files last updated: 1748635923.4413795

Stub file last updated: 2025-07-07 01:10:13

## generate_audit_report

```python
async def generate_audit_report(report_type: str = "comprehensive", start_time: Optional[str] = None, end_time: Optional[str] = None, filters: Optional[Dict[str, Any]] = None, output_format: str = "json", output_path: Optional[str] = None, include_details: bool = True) -> Dict[str, Any]:
    """
    Generate an audit report based on audit logs.

Args:
    report_type: Type of report ('security', 'compliance', 'operational', 'comprehensive')
    start_time: Optional start time for the report period (ISO format)
    end_time: Optional end time for the report period (ISO format)
    filters: Optional filters to apply to the audit logs
    output_format: Format of the report ('json', 'html', 'pdf')
    output_path: Optional path to save the report

Returns:
    Dict containing information about the generated report
    """
```
* **Async:** True
* **Method:** False
* **Class:** N/A
