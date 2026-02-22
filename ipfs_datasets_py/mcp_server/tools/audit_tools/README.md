# Audit Tools

MCP tools for recording audit events and generating compliance reports. Thin wrappers around
`ipfs_datasets_py.audit`.

## Tools

| File | Function(s) | Description |
|------|-------------|-------------|
| `audit_tools.py` | `log_audit_event()`, `query_audit_log()`, `export_audit_log()` | Record and query audit events |
| `record_audit_event.py` | `record_audit_event()` | Record a single audit event with actor, action, resource, outcome |
| `generate_audit_report.py` | `generate_audit_report()` | Generate HTML/JSON compliance report from audit logs |

## Usage

```python
from ipfs_datasets_py.mcp_server.tools.audit_tools import (
    record_audit_event, generate_audit_report
)

# Record an event
await record_audit_event(
    actor="user_42",
    action="dataset.download",
    resource="ipfs://QmXxx",
    outcome="success",
    metadata={"bytes": 1024000}
)

# Generate a compliance report
report = await generate_audit_report(
    start_date="2024-01-01",
    end_date="2024-12-31",
    format="json",       # "json" | "html" | "csv"
    filter_actor="user_42"
)
```

## Core Module

- `ipfs_datasets_py.audit` — audit log storage and querying

## Status

| Tool | Status |
|------|--------|
| `record_audit_event` | ✅ Production ready |
| `generate_audit_report` | ✅ Production ready |
