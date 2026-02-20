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


__all__ = [
    "HealthStatus",
    "AlertSeverity",
    "SystemMetrics",
    "ServiceMetrics",
    "Alert",
    "MockMonitoringService",
]
