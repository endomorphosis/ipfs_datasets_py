# Monitoring Tools

MCP tools for system metrics collection, health checks, and alerting. Thin wrappers around
the monitoring subsystem.

## Tools

| File | Function(s) | Description |
|------|-------------|-------------|
| `monitoring_tools.py` | `get_system_metrics()`, `check_health()`, `get_service_status()` | CPU/memory/disk metrics, service health checks |
| `enhanced_monitoring_tools.py` | `get_metrics_history()`, `set_alert_threshold()`, `get_alert_conditions()`, `monitor_ipfs_node()`, … | Historical metrics, configurable alerting, IPFS node monitoring |

## Usage

```python
from ipfs_datasets_py.mcp_server.tools.monitoring_tools import (
    check_health, get_system_metrics
)

# Health check
health = await check_health()
# Returns: {"status": "healthy", "services": {"ipfs": "ok", "db": "ok"}, "uptime_s": 86400}

# System metrics
metrics = await get_system_metrics(include=["cpu", "memory", "disk", "network"])
# Returns: {"cpu_percent": 12.4, "memory_mb": 1234, "disk_free_gb": 450, ...}
```

### Enhanced monitoring

```python
from ipfs_datasets_py.mcp_server.tools.monitoring_tools import (
    get_metrics_history, set_alert_threshold
)

# Get last 24h of metrics
history = await get_metrics_history(
    metric="cpu_percent",
    hours=24,
    resolution="5m"         # 5-minute buckets
)

# Set an alert threshold
await set_alert_threshold(
    metric="memory_percent",
    threshold=85.0,
    action="discord",
    webhook_url="https://discord.com/api/webhooks/..."
)
```

## Core Module

- `ipfs_datasets_py.mcp_server.monitoring` — `EnhancedMetricsCollector`, alert helpers

## Dependencies

- `psutil` — CPU/memory/disk metrics (required)

## Status

| Tool | Status |
|------|--------|
| `monitoring_tools` | ✅ Production ready |
| `enhanced_monitoring_tools` | ✅ Production ready |
