"""
Monitoring Engine.

Domain models, enums, and the mock monitoring service used by the enhanced
monitoring tools.  Separated from MCP tool classes to allow independent
testing and reuse.

MCP tool classes (EnhancedHealthCheckTool etc.) live in enhanced_monitoring_tools.py.
"""

import logging
import time
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, asdict
from enum import Enum

try:
    import psutil
    HAVE_PSUTIL = True
except ImportError:
    psutil = None  # type: ignore[assignment]
    HAVE_PSUTIL = False

logger = logging.getLogger(__name__)


class HealthStatus(Enum):
    """System health status."""

    HEALTHY = "healthy"
    WARNING = "warning"
    CRITICAL = "critical"
    UNKNOWN = "unknown"


class AlertSeverity(Enum):
    """Alert severity levels."""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


@dataclass
class SystemMetrics:
    """System metrics container."""

    timestamp: datetime
    cpu_usage_percent: float
    memory_usage_percent: float
    disk_usage_percent: float
    network_io_bytes_sent: int
    network_io_bytes_recv: int
    disk_io_read_bytes: int
    disk_io_write_bytes: int
    load_average: List[float]
    uptime_seconds: float


@dataclass
class ServiceMetrics:
    """Service-specific metrics."""

    service_name: str
    status: str
    response_time_ms: float
    request_count: int
    error_count: int
    memory_usage_mb: float
    cpu_usage_percent: float
    threads_count: int


@dataclass
class Alert:
    """Alert information."""

    id: str
    severity: AlertSeverity
    title: str
    description: str
    timestamp: datetime
    source: str
    resolved: bool = False
    resolution_time: Optional[datetime] = None


class MockMonitoringService:
    """Mock monitoring service for development and testing."""

    def __init__(self):
        self.alerts: List[Alert] = []
        self.metrics_history: List[SystemMetrics] = []
        self.thresholds = {
            "cpu_usage_warning": 80.0,
            "cpu_usage_critical": 95.0,
            "memory_usage_warning": 85.0,
            "memory_usage_critical": 95.0,
            "disk_usage_warning": 90.0,
            "disk_usage_critical": 98.0,
            "response_time_warning": 1000.0,
            "response_time_critical": 5000.0,
        }
        self.services = [
            "ipfs_daemon",
            "vector_store",
            "cache_service",
            "workflow_engine",
            "mcp_server",
        ]

    async def get_system_metrics(self) -> SystemMetrics:
        """Get current system metrics."""
        if not HAVE_PSUTIL:
            return SystemMetrics(
                timestamp=datetime.now(),
                cpu_usage_percent=0.0, memory_usage_percent=0.0,
                disk_usage_percent=0.0, network_io_bytes_sent=0,
                network_io_bytes_recv=0, disk_io_read_bytes=0,
                disk_io_write_bytes=0, load_average=[0.0, 0.0, 0.0],
                uptime_seconds=0.0,
            )
        return SystemMetrics(
            timestamp=datetime.now(),
            cpu_usage_percent=psutil.cpu_percent(interval=0.1),
            memory_usage_percent=psutil.virtual_memory().percent,
            disk_usage_percent=psutil.disk_usage("/").percent,
            network_io_bytes_sent=psutil.net_io_counters().bytes_sent,
            network_io_bytes_recv=psutil.net_io_counters().bytes_recv,
            disk_io_read_bytes=psutil.disk_io_counters().read_bytes,
            disk_io_write_bytes=psutil.disk_io_counters().write_bytes,
            load_average=list(psutil.getloadavg()),
            uptime_seconds=time.time() - psutil.boot_time(),
        )

    async def get_service_metrics(
        self, service_name: Optional[str] = None
    ) -> List[ServiceMetrics]:
        """Get service-specific metrics."""
        if service_name and service_name not in self.services:
            raise ValueError(f"Unknown service: {service_name}")

        services_to_check = [service_name] if service_name else self.services
        metrics = []

        for svc in services_to_check:
            # Mock service metrics with deterministic variation
            metrics.append(
                ServiceMetrics(
                    service_name=svc,
                    status="running",
                    response_time_ms=45.6 + (hash(svc) % 50),
                    request_count=1000 + (hash(svc) % 500),
                    error_count=2 + (hash(svc) % 5),
                    memory_usage_mb=128.5 + (hash(svc) % 100),
                    cpu_usage_percent=15.2 + (hash(svc) % 20),
                    threads_count=8 + (hash(svc) % 12),
                )
            )

        return metrics

    async def check_health(self, include_services: bool = True) -> Dict[str, Any]:
        """Perform comprehensive health check."""
        system_metrics = await self.get_system_metrics()
        health_status = HealthStatus.HEALTHY
        issues = []

        # Check system thresholds
        if system_metrics.cpu_usage_percent > self.thresholds["cpu_usage_critical"]:
            health_status = HealthStatus.CRITICAL
            issues.append(f"CPU usage critical: {system_metrics.cpu_usage_percent:.1f}%")
        elif system_metrics.cpu_usage_percent > self.thresholds["cpu_usage_warning"]:
            health_status = HealthStatus.WARNING
            issues.append(f"CPU usage high: {system_metrics.cpu_usage_percent:.1f}%")

        if system_metrics.memory_usage_percent > self.thresholds["memory_usage_critical"]:
            health_status = HealthStatus.CRITICAL
            issues.append(
                f"Memory usage critical: {system_metrics.memory_usage_percent:.1f}%"
            )
        elif system_metrics.memory_usage_percent > self.thresholds["memory_usage_warning"]:
            if health_status == HealthStatus.HEALTHY:
                health_status = HealthStatus.WARNING
            issues.append(f"Memory usage high: {system_metrics.memory_usage_percent:.1f}%")

        if system_metrics.disk_usage_percent > self.thresholds["disk_usage_critical"]:
            health_status = HealthStatus.CRITICAL
            issues.append(f"Disk usage critical: {system_metrics.disk_usage_percent:.1f}%")
        elif system_metrics.disk_usage_percent > self.thresholds["disk_usage_warning"]:
            if health_status == HealthStatus.HEALTHY:
                health_status = HealthStatus.WARNING
            issues.append(f"Disk usage high: {system_metrics.disk_usage_percent:.1f}%")

        result: Dict[str, Any] = {
            "overall_status": health_status.value,
            "timestamp": system_metrics.timestamp.isoformat(),
            "system_metrics": asdict(system_metrics),
            "issues": issues,
            "checks_performed": ["cpu", "memory", "disk", "network"],
        }

        if include_services:
            service_metrics = await self.get_service_metrics()
            service_health = []

            for svc_metrics in service_metrics:
                svc_status = HealthStatus.HEALTHY
                svc_issues = []

                if svc_metrics.response_time_ms > self.thresholds["response_time_critical"]:
                    svc_status = HealthStatus.CRITICAL
                    svc_issues.append(
                        f"Response time critical: {svc_metrics.response_time_ms:.1f}ms"
                    )
                elif svc_metrics.response_time_ms > self.thresholds["response_time_warning"]:
                    svc_status = HealthStatus.WARNING
                    svc_issues.append(
                        f"Response time high: {svc_metrics.response_time_ms:.1f}ms"
                    )

                service_health.append(
                    {
                        "service_name": svc_metrics.service_name,
                        "status": svc_status.value,
                        "issues": svc_issues,
                        "metrics": asdict(svc_metrics),
                    }
                )

            result["service_health"] = service_health
            result["checks_performed"].append("services")

        return result

    async def get_alerts(
        self,
        severity: Optional[AlertSeverity] = None,
        resolved: Optional[bool] = None,
    ) -> List[Alert]:
        """Get system alerts."""
        # Generate deterministic mock alerts
        mock_alerts = [
            Alert(
                id="alert_001",
                severity=AlertSeverity.WARNING,
                title="High Memory Usage",
                description="Memory usage has exceeded 85% threshold",
                timestamp=datetime.now() - timedelta(minutes=15),
                source="system_monitor",
                resolved=False,
            ),
            Alert(
                id="alert_002",
                severity=AlertSeverity.INFO,
                title="Cache Cleanup Completed",
                description="Scheduled cache cleanup freed 256MB",
                timestamp=datetime.now() - timedelta(hours=2),
                source="cache_service",
                resolved=True,
                resolution_time=datetime.now() - timedelta(hours=2, minutes=5),
            ),
            Alert(
                id="alert_003",
                severity=AlertSeverity.ERROR,
                title="Service Response Time High",
                description="Vector store service response time exceeded 1000ms",
                timestamp=datetime.now() - timedelta(minutes=30),
                source="service_monitor",
                resolved=False,
            ),
        ]

        # Filter alerts based on parameters
        filtered_alerts = mock_alerts

        if severity:
            filtered_alerts = [a for a in filtered_alerts if a.severity == severity]

        if resolved is not None:
            filtered_alerts = [a for a in filtered_alerts if a.resolved == resolved]

        return filtered_alerts

    async def collect_metrics(
        self, time_window: str, aggregation: str = "average"
    ) -> Dict[str, Any]:
        """Collect and aggregate metrics over time window."""
        num_points = {
            "5m": 5,
            "15m": 15,
            "1h": 60,
            "6h": 72,
            "24h": 144,
        }.get(time_window, 60)

        # Generate mock time series data
        timestamps = []
        cpu_values = []
        memory_values = []
        disk_values = []

        base_time = datetime.now()
        for i in range(num_points):
            timestamps.append((base_time - timedelta(minutes=i)).isoformat())
            cpu_values.append(25.0 + (i % 10) * 3.5)
            memory_values.append(45.0 + (i % 8) * 2.8)
            disk_values.append(75.0 + (i % 5) * 1.2)

        timestamps.reverse()
        cpu_values.reverse()
        memory_values.reverse()
        disk_values.reverse()

        return {
            "time_window": time_window,
            "aggregation": aggregation,
            "data_points": num_points,
            "metrics": {
                "cpu_usage": {
                    "timestamps": timestamps,
                    "values": cpu_values,
                    "average": sum(cpu_values) / len(cpu_values),
                    "min": min(cpu_values),
                    "max": max(cpu_values),
                },
                "memory_usage": {
                    "timestamps": timestamps,
                    "values": memory_values,
                    "average": sum(memory_values) / len(memory_values),
                    "min": min(memory_values),
                    "max": max(memory_values),
                },
                "disk_usage": {
                    "timestamps": timestamps,
                    "values": disk_values,
                    "average": sum(disk_values) / len(disk_values),
                    "min": min(disk_values),
                    "max": max(disk_values),
                },
            },
        }


# ---------------------------------------------------------------------------
# Psutil-based health-check helpers — shared with monitoring_tools.py
# ---------------------------------------------------------------------------

async def _check_system_health() -> Dict[str, Any]:
    """Return overall system health (uptime, process count)."""
    if not HAVE_PSUTIL:
        return {"status": "healthy", "note": "psutil not available"}
    try:
        uptime_hours = (time.time() - psutil.boot_time()) / 3600
        status = "warning" if uptime_hours < 0.1 else "healthy"
        return {
            "status": status,
            "uptime_hours": round(uptime_hours, 2),
            "boot_time": datetime.fromtimestamp(psutil.boot_time()).isoformat(),
            "process_count": len(psutil.pids()),
        }
    except Exception as exc:
        return {"status": "error", "error": str(exc)}


async def _check_memory_health() -> Dict[str, Any]:
    """Return memory health (usage %, available GB, total GB)."""
    if not HAVE_PSUTIL:
        return {"status": "healthy", "note": "psutil not available"}
    try:
        mem = psutil.virtual_memory()
        if mem.percent > 90:
            status = "critical"
        elif mem.percent > 80:
            status = "warning"
        else:
            status = "healthy"
        return {
            "status": status,
            "usage_percent": mem.percent,
            "available_gb": round(mem.available / (1024 ** 3), 2),
            "total_gb": round(mem.total / (1024 ** 3), 2),
        }
    except Exception as exc:
        return {"status": "error", "error": str(exc)}


async def _check_cpu_health() -> Dict[str, Any]:
    """Return CPU health (usage %, count, load average)."""
    if not HAVE_PSUTIL:
        return {"status": "healthy", "note": "psutil not available"}
    try:
        cpu_pct = psutil.cpu_percent(interval=1)
        if cpu_pct > 95:
            status = "critical"
        elif cpu_pct > 85:
            status = "warning"
        else:
            status = "healthy"
        return {
            "status": status,
            "usage_percent": cpu_pct,
            "count": psutil.cpu_count(),
            "load_average": psutil.getloadavg() if hasattr(psutil, "getloadavg") else None,
        }
    except Exception as exc:
        return {"status": "error", "error": str(exc)}


async def _check_disk_health() -> Dict[str, Any]:
    """Return disk health (usage %, free GB, total GB)."""
    if not HAVE_PSUTIL:
        return {"status": "healthy", "note": "psutil not available"}
    try:
        disk = psutil.disk_usage("/")
        pct = (disk.used / disk.total) * 100
        if pct > 95:
            status = "critical"
        elif pct > 85:
            status = "warning"
        else:
            status = "healthy"
        return {
            "status": status,
            "usage_percent": round(pct, 2),
            "free_gb": round(disk.free / (1024 ** 3), 2),
            "total_gb": round(disk.total / (1024 ** 3), 2),
        }
    except Exception as exc:
        return {"status": "error", "error": str(exc)}


async def _check_network_health() -> Dict[str, Any]:
    """Return basic network I/O counters."""
    if not HAVE_PSUTIL:
        return {"status": "healthy", "note": "psutil not available"}
    try:
        net = psutil.net_io_counters()
        return {
            "status": "healthy",
            "bytes_sent": net.bytes_sent,
            "bytes_recv": net.bytes_recv,
            "packets_sent": net.packets_sent,
            "packets_recv": net.packets_recv,
        }
    except Exception as exc:
        return {"status": "error", "error": str(exc)}


async def _check_services_health() -> Dict[str, Any]:
    """Return mock health status for key services."""
    try:
        services = {
            "mcp_server": "healthy",
            "embedding_service": "healthy",
            "vector_store": "warning",
            "cache_service": "healthy",
        }
        healthy = sum(1 for s in services.values() if s == "healthy")
        total = len(services)
        if healthy < total * 0.5:
            overall = "critical"
        elif healthy < total:
            overall = "warning"
        else:
            overall = "healthy"
        return {
            "status": overall,
            "services": services,
            "healthy_services": healthy,
            "total_services": total,
        }
    except Exception as exc:
        return {"status": "error", "error": str(exc)}


async def _check_embeddings_health() -> Dict[str, Any]:
    """Return mock embeddings service health."""
    try:
        return {
            "status": "healthy",
            "active_models": 3,
            "endpoints_available": 5,
            "last_embedding_time": datetime.now().isoformat(),
            "cache_hit_rate": 85.5,
        }
    except Exception as exc:
        return {"status": "error", "error": str(exc)}


async def _check_vector_stores_health() -> Dict[str, Any]:
    """Return mock vector-store health."""
    try:
        stores = {
            "faiss": {"status": "healthy", "indices": 8, "size_mb": 245},
            "qdrant": {"status": "healthy", "collections": 5, "vectors": 10000},
            "elasticsearch": {"status": "warning", "indices": 3, "health": "yellow"},
        }
        return {
            "status": "healthy",
            "stores": stores,
            "total_stores": len(stores),
            "healthy_stores": sum(1 for s in stores.values() if s["status"] == "healthy"),
        }
    except Exception as exc:
        return {"status": "error", "error": str(exc)}


async def _check_service_status(service_name: str) -> Dict[str, Any]:
    """Return mock status for a named service."""
    try:
        import anyio
        import time as _time
        start = _time.time()
        await anyio.sleep(0.01)  # Simulate network delay
        response_ms = (_time.time() - start) * 1000
        if service_name == "vector_store":
            status, message = "warning", "High response times detected"
        elif service_name == "cache_service":
            status, message = "healthy", "Operating normally"
        else:
            status, message = "healthy", "Service operational"
        return {
            "status": status,
            "response_time": round(response_ms, 2),
            "message": message,
            "last_check": datetime.now().isoformat(),
        }
    except Exception as exc:
        return {"status": "error", "error": str(exc)}


async def _get_performance_metrics() -> Dict[str, Any]:
    """Return current performance metrics snapshot."""
    if not HAVE_PSUTIL:
        return {"note": "psutil not available", "cpu_usage": 0.0, "memory_usage": 0.0}
    try:
        return {
            "cpu_usage": psutil.cpu_percent(interval=0.1),
            "memory_usage": psutil.virtual_memory().percent,
            "disk_usage": (psutil.disk_usage("/").used / psutil.disk_usage("/").total) * 100,
            "process_count": len(psutil.pids()),
            "network_connections": len(psutil.net_connections()),
        }
    except Exception as exc:
        return {"error": str(exc)}


async def _generate_health_recommendations(health_results: Dict[str, Any]) -> List[str]:
    """Generate actionable recommendations from *health_results*."""
    recommendations: List[str] = []
    try:
        for component, data in health_results.get("components", {}).items():
            status = data.get("status", "unknown")
            if status == "critical":
                pct = data.get("usage_percent", 0)
                if component == "memory" and pct > 90:
                    recommendations.append(
                        "Critical: Memory usage above 90%. Consider restarting services or adding more RAM."
                    )
                elif component == "cpu" and pct > 95:
                    recommendations.append(
                        "Critical: CPU usage above 95%. Check for runaway processes."
                    )
                elif component == "disk" and pct > 95:
                    recommendations.append(
                        "Critical: Disk usage above 95%. Clean up disk space immediately."
                    )
            elif status == "warning":
                pct = data.get("usage_percent", 0)
                if component == "memory" and pct > 80:
                    recommendations.append("Warning: Memory usage above 80%. Monitor closely.")
                elif component == "cpu" and pct > 85:
                    recommendations.append(
                        "Warning: CPU usage above 85%. Consider load balancing."
                    )

        if health_results.get("health_score", 100) < 80:
            recommendations.append(
                "Overall system health below 80%. Review all component statuses."
            )

        if not recommendations:
            recommendations.append("System appears healthy. Continue regular monitoring.")
    except Exception as exc:
        recommendations.append(f"Error generating recommendations: {exc}")

    return recommendations


__all__ = [
    "HealthStatus",
    "AlertSeverity",
    "SystemMetrics",
    "ServiceMetrics",
    "Alert",
    "MockMonitoringService",
    "_check_system_health",
    "_check_memory_health",
    "_check_cpu_health",
    "_check_disk_health",
    "_check_network_health",
    "_check_services_health",
    "_check_embeddings_health",
    "_check_vector_stores_health",
    "_check_service_status",
    "_get_performance_metrics",
    "_generate_health_recommendations",
]


# ---------------------------------------------------------------------------
# High-level async API — canonical business-logic location
# ---------------------------------------------------------------------------

# Shared in-process metrics store (MCP tools import this directly)
METRICS_STORAGE: Dict[str, Any] = {
    "system_metrics": [],
    "performance_metrics": [],
    "service_health": {},
    "alerts": [],
}


async def health_check(
    check_type: str = "basic",
    components: Optional[List[str]] = None,
    include_metrics: bool = True,
) -> Dict[str, Any]:
    """Perform system health checks and return consolidated status."""
    from datetime import datetime as _dt
    timestamp = _dt.now()
    all_components = ["system", "memory", "cpu", "disk", "network", "services", "embeddings", "vector_stores"]
    if check_type == "basic":
        components_to_check = ["system", "memory", "cpu", "services"]
    elif check_type == "all":
        components_to_check = all_components
    else:
        components_to_check = components or all_components
    health_results: Dict[str, Any] = {
        "timestamp": timestamp.isoformat(),
        "check_type": check_type,
        "overall_status": "healthy",
        "components": {},
    }
    _component_fn = {
        "system": _check_system_health,
        "memory": _check_memory_health,
        "cpu": _check_cpu_health,
        "disk": _check_disk_health,
        "network": _check_network_health,
        "services": _check_services_health,
        "embeddings": _check_embeddings_health,
        "vector_stores": _check_vector_stores_health,
    }
    for component in components_to_check:
        try:
            fn = _component_fn.get(component)
            if fn is not None:
                health_results["components"][component] = await fn()
            else:
                health_results["components"][component] = {"status": "unknown"}
        except Exception as e:
            health_results["components"][component] = {"status": "error", "error": str(e)}
    # Determine overall status
    statuses = [c.get("status", "unknown") for c in health_results["components"].values()]
    if any(s == "critical" for s in statuses):
        health_results["overall_status"] = "critical"
    elif any(s in ("degraded", "warning") for s in statuses):
        health_results["overall_status"] = "degraded"
    if include_metrics:
        health_results["metrics_summary"] = await _get_performance_metrics()
    # Persist to shared store
    METRICS_STORAGE["system_metrics"].append({
        "timestamp": timestamp.isoformat(),
        "overall_status": health_results["overall_status"],
        "health_score": 1.0 if health_results["overall_status"] == "healthy" else 0.5,
    })
    return {"success": True, "health_check": health_results,
            "recommendations": await _generate_health_recommendations(health_results)}


async def get_performance_metrics(
    metric_types: Optional[List[str]] = None,
    time_range: str = "1h",
    include_history: bool = True,
) -> Dict[str, Any]:
    """Get current system performance metrics."""
    from datetime import datetime as _dt
    timestamp = _dt.now()
    if not metric_types:
        metric_types = ["cpu", "memory", "disk", "network", "system"]
    raw = await _get_performance_metrics()
    metrics: Dict[str, Any] = {
        "timestamp": timestamp.isoformat(),
        "time_range": time_range,
        "current_metrics": {mt: raw.get(mt, {"status": "unavailable"}) for mt in metric_types},
        "summary": raw.get("summary", {}),
    }
    METRICS_STORAGE["performance_metrics"].append({
        "timestamp": timestamp.isoformat(),
        "metrics": metrics["current_metrics"],
    })
    return {"success": True, "performance_metrics": metrics}


async def monitor_services(
    services: Optional[List[str]] = None,
    check_interval: int = 30,
) -> Dict[str, Any]:
    """Monitor specific services and return health status."""
    from datetime import datetime as _dt
    timestamp = _dt.now()
    default_services = ["embedding_service", "vector_store", "ipfs_node", "mcp_server", "cache_service"]
    services = services or default_services
    service_statuses: Dict[str, Any] = {}
    for service in services:
        try:
            status = await _check_service_status(service)
            service_statuses[service] = status
            METRICS_STORAGE["service_health"][service] = {
                "last_check": timestamp.isoformat(),
                "status": status.get("status", "unknown"),
                "response_time": status.get("response_time", 0),
            }
        except Exception as e:
            service_statuses[service] = {"status": "error", "error": str(e)}
    healthy_count = sum(1 for s in service_statuses.values() if s.get("status") == "healthy")
    return {
        "success": True,
        "service_statuses": service_statuses,
        "monitoring_results": service_statuses,  # backward-compat alias
        "total_services": len(services),
        "healthy_services": healthy_count,
        "check_interval": check_interval,
        "checked_at": timestamp.isoformat(),
    }


async def generate_monitoring_report(
    report_type: str = "summary",
    time_period: str = "24h",
) -> Dict[str, Any]:
    """Generate a consolidated monitoring report from in-process metrics store."""
    from datetime import datetime as _dt, timedelta as _td
    timestamp = _dt.now()
    _period_map = {"1h": _td(hours=1), "6h": _td(hours=6), "24h": _td(hours=24), "7d": _td(days=7)}
    start_time = timestamp - _period_map.get(time_period, _td(hours=24))
    report: Dict[str, Any] = {
        "report_type": report_type,
        "time_period": time_period,
        "generated_at": timestamp.isoformat(),
        "start_time": start_time.isoformat(),
        "end_time": timestamp.isoformat(),
    }
    if report_type in ("summary", "detailed"):
        recent = [m for m in METRICS_STORAGE["system_metrics"]
                  if _dt.fromisoformat(m["timestamp"]) >= start_time]
        if recent:
            report["health_summary"] = {
                "average_health_score": round(sum(m["health_score"] for m in recent) / len(recent), 2),
                "total_checks": len(recent),
                "current_status": recent[-1]["overall_status"],
            }
        else:
            report["health_summary"] = {"message": "No health metrics for this period"}
    if report_type in ("performance", "detailed"):
        recent_perf = [m for m in METRICS_STORAGE["performance_metrics"]
                       if _dt.fromisoformat(m["timestamp"]) >= start_time]
        if recent_perf:
            report["performance_summary"] = {
                "metrics_collected": len(recent_perf),
                "latest_cpu": recent_perf[-1]["metrics"].get("cpu", {}).get("usage_percent", 0),
                "latest_memory": recent_perf[-1]["metrics"].get("memory", {}).get("usage_percent", 0),
            }
        else:
            report["performance_summary"] = {"message": "No performance metrics for this period"}
    if report_type in ("alerts", "detailed"):
        recent_alerts = [a for a in METRICS_STORAGE["alerts"]
                         if _dt.fromisoformat(a.get("timestamp", timestamp.isoformat())) >= start_time]
        report["alerts_summary"] = {
            "total_alerts": len(recent_alerts),
            "critical_alerts": sum(1 for a in recent_alerts if a.get("severity") == "critical"),
            "warning_alerts": sum(1 for a in recent_alerts if a.get("severity") == "warning"),
            "recent_alerts": recent_alerts[-5:],
        }
    report["service_health_summary"] = {
        "services_monitored": len(METRICS_STORAGE["service_health"]),
        "healthy_services": sum(1 for s in METRICS_STORAGE["service_health"].values()
                                if s.get("status") == "healthy"),
        "service_details": METRICS_STORAGE["service_health"],
    }
    return {"success": True, "monitoring_report": report}


__all__ = [
    "HealthStatus",
    "AlertSeverity",
    "SystemMetrics",
    "ServiceMetrics",
    "Alert",
    "MockMonitoringService",
    "METRICS_STORAGE",
    "_check_system_health",
    "_check_memory_health",
    "_check_cpu_health",
    "_check_disk_health",
    "_check_network_health",
    "_check_services_health",
    "_check_embeddings_health",
    "_check_vector_stores_health",
    "_check_service_status",
    "_get_performance_metrics",
    "_generate_health_recommendations",
    "health_check",
    "get_performance_metrics",
    "monitor_services",
    "generate_monitoring_report",
]
