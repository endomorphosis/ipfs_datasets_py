"""
Monitoring Engine.

Domain models, enums, and the mock monitoring service used by the enhanced
monitoring tools.  Separated from MCP tool classes to allow independent
testing and reuse.

MCP tool classes (EnhancedHealthCheckTool etc.) live in enhanced_monitoring_tools.py.
"""

import logging
import time
import psutil
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, asdict
from enum import Enum

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
