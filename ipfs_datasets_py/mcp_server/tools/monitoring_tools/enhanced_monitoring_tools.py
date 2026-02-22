# ipfs_datasets_py/mcp_server/tools/monitoring_tools/enhanced_monitoring_tools.py
"""
Enhanced monitoring tools — standalone async MCP functions.

Business logic (MockMonitoringService, HealthStatus, AlertSeverity, etc.)
lives in ipfs_datasets_py.monitoring_engine.
"""
from __future__ import annotations

import logging
from dataclasses import asdict
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

# Re-export engine symbols so existing imports keep working.
from .monitoring_engine import (  # noqa: F401
    Alert,
    AlertSeverity,
    HealthStatus,
    MockMonitoringService,
    ServiceMetrics,
    SystemMetrics,
)

logger = logging.getLogger(__name__)

_DEFAULT_MONITORING_SERVICE = MockMonitoringService()


async def check_health(
    include_services: bool = True,
    include_metrics: bool = True,
    check_depth: str = "standard",
    services: Optional[List[str]] = None,
    include_recommendations: bool = True,
) -> Dict[str, Any]:
    """Perform a comprehensive system health check."""
    health_data = await _DEFAULT_MONITORING_SERVICE.check_health(include_services)
    result: Dict[str, Any] = {
        "health_check": health_data,
        "check_depth": check_depth,
        "timestamp": datetime.now().isoformat(),
    }
    if include_recommendations:
        recs: List[str] = []
        overall = health_data["overall_status"]
        if overall == "warning":
            recs += ["Monitor system resources closely", "Consider scaling resources if issues persist"]
        elif overall == "critical":
            recs += ["Immediate action required to resolve critical issues", "Consider emergency scaling or service restart"]
        else:
            recs.append("System is healthy, continue monitoring")
        sm = health_data["system_metrics"]
        if sm["cpu_usage_percent"] > 70:
            recs.append("High CPU usage detected - investigate high-load processes")
        if sm["memory_usage_percent"] > 80:
            recs.append("High memory usage - consider memory optimization")
        if sm["disk_usage_percent"] > 85:
            recs.append("Disk space running low - cleanup or expand storage")
        result["recommendations"] = recs
    if check_depth == "comprehensive":
        result["diagnostics"] = {
            "performance_score": 85.2,
            "availability_percent": 99.8,
            "reliability_index": 0.95,
            "recent_incidents": 2,
            "mttr_minutes": 12.5,
            "mtbf_hours": 168.3,
        }
    return result


async def collect_metrics(
    time_window: str = "1h",
    metrics: Optional[List[str]] = None,
    aggregation: str = "average",
    include_trends: bool = True,
    include_anomalies: bool = False,
    export_format: str = "json",
) -> Dict[str, Any]:
    """Collect and analyse system metrics."""
    metrics_data = await _DEFAULT_MONITORING_SERVICE.collect_metrics(time_window, aggregation)
    result: Dict[str, Any] = {
        "metrics_collection": metrics_data,
        "collection_config": {"time_window": time_window, "metrics_requested": metrics or ["cpu", "memory", "disk"], "aggregation": aggregation},
    }
    if include_trends:
        cpu_v = metrics_data["metrics"]["cpu_usage"]["values"]
        mem_v = metrics_data["metrics"]["memory_usage"]["values"]
        result["trend_analysis"] = {
            "cpu_trend": "stable" if max(cpu_v) - min(cpu_v) < 10 else "volatile",
            "memory_trend": "increasing" if mem_v[-1] > mem_v[0] else "stable",
            "overall_trend": "stable",
            "trend_confidence": 0.85,
        }
    if include_anomalies:
        result["anomaly_detection"] = {
            "anomalies_found": 2,
            "anomalies": [
                {"timestamp": (datetime.now() - timedelta(minutes=25)).isoformat(), "metric": "cpu_usage", "value": 89.5, "expected_range": [20, 60], "severity": "warning"},
                {"timestamp": (datetime.now() - timedelta(minutes=45)).isoformat(), "metric": "memory_usage", "value": 78.2, "expected_range": [30, 70], "severity": "info"},
            ],
        }
    if export_format != "json":
        result["export_info"] = {
            "format": export_format,
            "export_path": f"/tmp/metrics_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.{export_format}",
            "export_size": "2.3MB" if export_format == "csv" else "1.8MB",
        }
    return result


async def manage_alerts(
    action: str,
    severity_filter: Optional[str] = None,
    resolved_filter: Optional[bool] = None,
    time_range: str = "24h",
    include_metrics: bool = True,
    alert_id: Optional[str] = None,
    threshold_config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """List, acknowledge, resolve alerts, or configure thresholds."""
    threshold_config = threshold_config or {}
    if action == "list":
        severity_enum = AlertSeverity(severity_filter) if severity_filter else None
        alerts = await _DEFAULT_MONITORING_SERVICE.get_alerts(severity_enum, resolved_filter)
        result: Dict[str, Any] = {
            "action": "list",
            "alerts": [asdict(a) for a in alerts],
            "total_count": len(alerts),
            "filters_applied": {"severity": severity_filter, "resolved": resolved_filter, "time_range": time_range},
        }
        if include_metrics:
            result["alert_metrics"] = {
                "critical_count": sum(1 for a in alerts if a.severity == AlertSeverity.CRITICAL),
                "warning_count": sum(1 for a in alerts if a.severity == AlertSeverity.WARNING),
                "info_count": sum(1 for a in alerts if a.severity == AlertSeverity.INFO),
                "resolved_count": sum(1 for a in alerts if a.resolved),
                "average_resolution_time_minutes": 15.3,
                "escalation_rate": 0.12,
            }
        return result
    if action in ("acknowledge", "resolve"):
        if not alert_id:
            raise ValueError(f"alert_id required for {action} action")
        return {"action": action, "alert_id": alert_id, "success": True, "timestamp": datetime.now().isoformat(), "message": f"Alert {alert_id} {action}d successfully"}
    if action == "configure_thresholds":
        if threshold_config:
            _DEFAULT_MONITORING_SERVICE.thresholds.update(threshold_config)
        return {"action": "configure_thresholds", "updated_thresholds": threshold_config, "current_thresholds": _DEFAULT_MONITORING_SERVICE.thresholds, "restart_required": False}
    return {"action": action, "success": True, "message": f"Alert {action} operation completed"}


# Backward-compatible class shims
class EnhancedHealthCheckTool:
    """Backward-compatible shim."""
    async def execute(self, parameters: Dict[str, Any]) -> Dict[str, Any]:  # noqa: D102
        return await check_health(**{k: v for k, v in parameters.items() if k in ("include_services", "include_metrics", "check_depth", "services", "include_recommendations")})


class EnhancedMetricsCollectionTool:
    """Backward-compatible shim."""
    async def execute(self, parameters: Dict[str, Any]) -> Dict[str, Any]:  # noqa: D102
        return await collect_metrics(parameters.get("time_window", "1h"), parameters.get("metrics"), parameters.get("aggregation", "average"), parameters.get("include_trends", True), parameters.get("include_anomalies", False), parameters.get("export_format", "json"))


class EnhancedAlertManagementTool:
    """Backward-compatible shim."""
    async def execute(self, parameters: Dict[str, Any]) -> Dict[str, Any]:  # noqa: D102
        return await manage_alerts(parameters["action"], parameters.get("severity_filter"), parameters.get("resolved_filter"), parameters.get("time_range", "24h"), parameters.get("include_metrics", True), parameters.get("alert_id"), parameters.get("threshold_config", {}))


__all__ = [
    "check_health",
    "collect_metrics",
    "manage_alerts",
    "EnhancedHealthCheckTool",
    "EnhancedMetricsCollectionTool",
    "EnhancedAlertManagementTool",
    "HealthStatus",
    "AlertSeverity",
    "SystemMetrics",
    "ServiceMetrics",
    "Alert",
    "MockMonitoringService",
]
