# Function and Class stubs from '<repo-root>/ipfs_datasets_py/ipfs_datasets_py/mcp_server/tools/audit_tools/audit_tools.py'

Files last updated: 1751408933.6764565

Stub file last updated: 2025-07-07 01:10:13

## AuditTool

```python
class AuditTool:
    """
    A tool for performing audit-related tasks.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## audit_tools

```python
async def audit_tools(target: str = "."):
    """
    A tool for performing audit-related tasks.
    """
```
* **Async:** True
* **Method:** False
* **Class:** N/A

## perform_audit

```python
def perform_audit(self, target: str) -> str:
    """
    Performs an audit on the specified target.

Args:
    target: The target to audit (e.g., a file path, a system component).

Returns:
    A string containing the audit results.
    """
```
* **Async:** False
* **Method:** True
* **Class:** AuditTool
