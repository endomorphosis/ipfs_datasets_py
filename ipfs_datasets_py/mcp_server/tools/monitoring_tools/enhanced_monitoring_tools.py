# ipfs_datasets_py/mcp_server/tools/monitoring_tools/enhanced_monitoring_tools.py
"""
Enhanced monitoring and system health tools.
Migrated and enhanced from a legacy tooling codebase with production features.

Domain models and the mock monitoring service have been extracted to
monitoring_engine.py; they are re-exported here so existing import paths
continue to work unchanged.
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
from dataclasses import asdict

from ..tool_wrapper import EnhancedBaseMCPTool
from ...validators import EnhancedParameterValidator
from ...monitoring import EnhancedMetricsCollector

# Re-export engine symbols so existing imports keep working.
from .monitoring_engine import (  # noqa: F401
    HealthStatus,
    AlertSeverity,
    SystemMetrics,
    ServiceMetrics,
    Alert,
    MockMonitoringService,
)

logger = logging.getLogger(__name__)

class EnhancedHealthCheckTool(EnhancedBaseMCPTool):
    """Enhanced tool for comprehensive system health monitoring."""
    
    def __init__(self, monitoring_service=None, validator=None, metrics_collector=None):
        super().__init__(
            name="enhanced_health_check",
            description="Perform comprehensive health checks on system and services with detailed diagnostics.",
            category="monitoring",
            version="1.0.0",
            validator=validator or EnhancedParameterValidator(),
            metrics_collector=metrics_collector or EnhancedMetricsCollector()
        )
        
        self.monitoring_service = monitoring_service or MockMonitoringService()
        
        self.input_schema = {
            "type": "object",
            "properties": {
                "include_services": {
                    "type": "boolean",
                    "description": "Include service-specific health checks",
                    "default": True
                },
                "include_metrics": {
                    "type": "boolean",
                    "description": "Include detailed system metrics",
                    "default": True
                },
                "check_depth": {
                    "type": "string",
                    "description": "Depth of health check",
                    "enum": ["basic", "standard", "comprehensive"],
                    "default": "standard"
                },
                "services": {
                    "type": "array",
                    "description": "Specific services to check (empty for all)",
                    "items": {
                        "type": "string"
                    },
                    "default": []
                },
                "include_recommendations": {
                    "type": "boolean",
                    "description": "Include optimization recommendations",
                    "default": True
                }
            }
        }
    
    async def _execute_impl(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """Perform comprehensive health check."""
        include_services = parameters.get("include_services", True)
        include_metrics = parameters.get("include_metrics", True)
        check_depth = parameters.get("check_depth", "standard")
        services = parameters.get("services", [])
        include_recommendations = parameters.get("include_recommendations", True)
        
        health_data = await self.monitoring_service.check_health(include_services)
        
        result = {
            "health_check": health_data,
            "check_depth": check_depth,
            "timestamp": datetime.now().isoformat()
        }
        
        if include_recommendations:
            recommendations = []
            
            # Generate recommendations based on health status
            if health_data["overall_status"] == "warning":
                recommendations.append("Monitor system resources closely")
                recommendations.append("Consider scaling resources if issues persist")
            elif health_data["overall_status"] == "critical":
                recommendations.append("Immediate action required to resolve critical issues")
                recommendations.append("Consider emergency scaling or service restart")
            else:
                recommendations.append("System is healthy, continue monitoring")
            
            # Add specific recommendations based on metrics
            system_metrics = health_data["system_metrics"]
            if system_metrics["cpu_usage_percent"] > 70:
                recommendations.append("High CPU usage detected - investigate high-load processes")
            if system_metrics["memory_usage_percent"] > 80:
                recommendations.append("High memory usage - consider memory optimization")
            if system_metrics["disk_usage_percent"] > 85:
                recommendations.append("Disk space running low - cleanup or expand storage")
            
            result["recommendations"] = recommendations
        
        if check_depth == "comprehensive":
            # Add additional diagnostic information
            result["diagnostics"] = {
                "performance_score": 85.2,
                "availability_percent": 99.8,
                "reliability_index": 0.95,
                "recent_incidents": 2,
                "mttr_minutes": 12.5,
                "mtbf_hours": 168.3
            }
        
        return result

class EnhancedMetricsCollectionTool(EnhancedBaseMCPTool):
    """Enhanced tool for collecting and analyzing system metrics."""
    
    def __init__(self, monitoring_service=None, validator=None, metrics_collector=None):
        super().__init__(
            name="enhanced_metrics_collection",
            description="Collect, aggregate, and analyze system and service metrics over time.",
            category="monitoring",
            version="1.0.0",
            validator=validator or EnhancedParameterValidator(),
            metrics_collector=metrics_collector or EnhancedMetricsCollector()
        )
        
        self.monitoring_service = monitoring_service or MockMonitoringService()
        
        self.input_schema = {
            "type": "object",
            "properties": {
                "time_window": {
                    "type": "string",
                    "description": "Time window for metrics collection",
                    "enum": ["5m", "15m", "1h", "6h", "24h", "7d"],
                    "default": "1h"
                },
                "metrics": {
                    "type": "array",
                    "description": "Specific metrics to collect",
                    "items": {
                        "type": "string",
                        "enum": ["cpu", "memory", "disk", "network", "services", "all"]
                    },
                    "default": ["cpu", "memory", "disk"]
                },
                "aggregation": {
                    "type": "string",
                    "description": "Aggregation method",
                    "enum": ["average", "min", "max", "sum", "count"],
                    "default": "average"
                },
                "include_trends": {
                    "type": "boolean",
                    "description": "Include trend analysis",
                    "default": True
                },
                "include_anomalies": {
                    "type": "boolean",
                    "description": "Include anomaly detection",
                    "default": False
                },
                "export_format": {
                    "type": "string",
                    "description": "Export format for metrics data",
                    "enum": ["json", "csv", "prometheus"],
                    "default": "json"
                }
            }
        }
    
    async def _execute_impl(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """Collect and analyze metrics."""
        time_window = parameters.get("time_window", "1h")
        metrics = parameters.get("metrics", ["cpu", "memory", "disk"])
        aggregation = parameters.get("aggregation", "average")
        include_trends = parameters.get("include_trends", True)
        include_anomalies = parameters.get("include_anomalies", False)
        export_format = parameters.get("export_format", "json")
        
        metrics_data = await self.monitoring_service.collect_metrics(time_window, aggregation)
        
        result = {
            "metrics_collection": metrics_data,
            "collection_config": {
                "time_window": time_window,
                "metrics_requested": metrics,
                "aggregation": aggregation
            }
        }
        
        if include_trends:
            # Add trend analysis
            cpu_values = metrics_data["metrics"]["cpu_usage"]["values"]
            memory_values = metrics_data["metrics"]["memory_usage"]["values"]
            
            result["trend_analysis"] = {
                "cpu_trend": "stable" if max(cpu_values) - min(cpu_values) < 10 else "volatile",
                "memory_trend": "increasing" if memory_values[-1] > memory_values[0] else "stable",
                "overall_trend": "stable",
                "trend_confidence": 0.85
            }
        
        if include_anomalies:
            # Mock anomaly detection
            result["anomaly_detection"] = {
                "anomalies_found": 2,
                "anomalies": [
                    {
                        "timestamp": (datetime.now() - timedelta(minutes=25)).isoformat(),
                        "metric": "cpu_usage",
                        "value": 89.5,
                        "expected_range": [20, 60],
                        "severity": "warning"
                    },
                    {
                        "timestamp": (datetime.now() - timedelta(minutes=45)).isoformat(),
                        "metric": "memory_usage",
                        "value": 78.2,
                        "expected_range": [30, 70],
                        "severity": "info"
                    }
                ]
            }
        
        if export_format != "json":
            result["export_info"] = {
                "format": export_format,
                "export_path": f"/tmp/metrics_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.{export_format}",
                "export_size": "2.3MB" if export_format == "csv" else "1.8MB"
            }
        
        return result

class EnhancedAlertManagementTool(EnhancedBaseMCPTool):
    """Enhanced tool for managing system alerts and notifications."""
    
    def __init__(self, monitoring_service=None, validator=None, metrics_collector=None):
        super().__init__(
            name="enhanced_alert_management",
            description="Manage system alerts, notifications, and alert configurations.",
            category="monitoring", 
            version="1.0.0",
            validator=validator or EnhancedParameterValidator(),
            metrics_collector=metrics_collector or EnhancedMetricsCollector()
        )
        
        self.monitoring_service = monitoring_service or MockMonitoringService()
        
        self.input_schema = {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "description": "Alert management action",
                    "enum": ["list", "get", "acknowledge", "resolve", "create", "configure_thresholds"]
                },
                "alert_id": {
                    "type": "string",
                    "description": "Alert ID (required for get, acknowledge, resolve actions)"
                },
                "severity_filter": {
                    "type": "string",
                    "description": "Filter alerts by severity",
                    "enum": ["info", "warning", "error", "critical"]
                },
                "resolved_filter": {
                    "type": "boolean",
                    "description": "Filter by resolution status"
                },
                "time_range": {
                    "type": "string",
                    "description": "Time range for alert listing",
                    "enum": ["1h", "6h", "24h", "7d", "30d"],
                    "default": "24h"
                },
                "include_metrics": {
                    "type": "boolean",
                    "description": "Include alert metrics and statistics",
                    "default": True
                },
                "threshold_config": {
                    "type": "object",
                    "description": "Alert threshold configuration",
                    "properties": {
                        "cpu_usage_warning": {"type": "number", "minimum": 0, "maximum": 100},
                        "cpu_usage_critical": {"type": "number", "minimum": 0, "maximum": 100},
                        "memory_usage_warning": {"type": "number", "minimum": 0, "maximum": 100},
                        "memory_usage_critical": {"type": "number", "minimum": 0, "maximum": 100}
                    }
                }
            },
            "required": ["action"]
        }
    
    async def _execute_impl(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """Manage alerts."""
        action = parameters["action"]
        
        if action == "list":
            severity_filter = parameters.get("severity_filter")
            resolved_filter = parameters.get("resolved_filter")
            time_range = parameters.get("time_range", "24h")
            include_metrics = parameters.get("include_metrics", True)
            
            severity_enum = AlertSeverity(severity_filter) if severity_filter else None
            alerts = await self.monitoring_service.get_alerts(severity_enum, resolved_filter)
            
            result = {
                "action": "list",
                "alerts": [asdict(alert) for alert in alerts],
                "total_count": len(alerts),
                "filters_applied": {
                    "severity": severity_filter,
                    "resolved": resolved_filter,
                    "time_range": time_range
                }
            }
            
            if include_metrics:
                result["alert_metrics"] = {
                    "critical_count": sum(1 for a in alerts if a.severity == AlertSeverity.CRITICAL),
                    "warning_count": sum(1 for a in alerts if a.severity == AlertSeverity.WARNING),
                    "info_count": sum(1 for a in alerts if a.severity == AlertSeverity.INFO),
                    "resolved_count": sum(1 for a in alerts if a.resolved),
                    "average_resolution_time_minutes": 15.3,
                    "escalation_rate": 0.12
                }
            
            return result
        
        elif action in ["acknowledge", "resolve"]:
            alert_id = parameters.get("alert_id")
            if not alert_id:
                raise ValueError(f"alert_id required for {action} action")
            
            return {
                "action": action,
                "alert_id": alert_id,
                "success": True,
                "timestamp": datetime.now().isoformat(),
                "message": f"Alert {alert_id} {action}d successfully"
            }
        
        elif action == "configure_thresholds":
            threshold_config = parameters.get("threshold_config", {})
            
            if threshold_config:
                self.monitoring_service.thresholds.update(threshold_config)
            
            return {
                "action": "configure_thresholds",
                "updated_thresholds": threshold_config,
                "current_thresholds": self.monitoring_service.thresholds,
                "restart_required": False
            }
        
        else:
            return {
                "action": action,
                "success": True,
                "message": f"Alert {action} operation completed"
            }

# Export the enhanced tools
__all__ = [
    "EnhancedHealthCheckTool",
    "EnhancedMetricsCollectionTool",
    "EnhancedAlertManagementTool",
    "HealthStatus",
    "AlertSeverity",
    "SystemMetrics",
    "ServiceMetrics",
    "Alert",
    "MockMonitoringService"
]
