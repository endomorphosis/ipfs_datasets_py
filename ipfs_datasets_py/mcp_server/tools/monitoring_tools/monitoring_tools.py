# ipfs_datasets_py/mcp_server/tools/monitoring_tools/monitoring_tools.py
"""
System monitoring and health check tools (thin MCP wrapper).

Business logic — helper functions, psutil calls, data models — lives in
ipfs_datasets_py.monitoring_engine.  This module is a thin MCP wrapper
that validates inputs, delegates to the engine, and formats responses.
"""

import logging
import psutil
import time
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta

from ipfs_datasets_py.monitoring_engine import (  # noqa: F401
    HealthStatus,
    AlertSeverity,
    SystemMetrics,
    ServiceMetrics,
    Alert,
    MockMonitoringService,
    _check_system_health,
    _check_memory_health,
    _check_cpu_health,
    _check_disk_health,
    _check_network_health,
    _check_services_health,
    _check_embeddings_health,
    _check_vector_stores_health,
    _check_service_status,
    _get_performance_metrics,
    _generate_health_recommendations,
)

logger = logging.getLogger(__name__)

# Global metrics storage (MCP-layer concern — not part of the engine)
METRICS_STORAGE: Dict[str, Any] = {
    "system_metrics": [],
    "performance_metrics": [],
    "service_health": {},
    "alerts": [],
}


async def health_check(
    check_type: str = "basic",
    components: Optional[List[str]] = None,
    include_metrics: bool = True
) -> Dict[str, Any]:
    """
    Perform comprehensive health checks on system components.
    
    Args:
        check_type: Type of health check (basic, detailed, specific, all)
        components: Specific components to check
        include_metrics: Include detailed metrics in response
        
    Returns:
        Dict containing health check results
    """
    try:
        timestamp = datetime.now()
        
        health_results = {
            "timestamp": timestamp.isoformat(),
            "check_type": check_type,
            "overall_status": "healthy",
            "components": {}
        }
        
        # Determine which components to check
        all_components = ["system", "memory", "cpu", "disk", "network", "services", "embeddings", "vector_stores"]
        components_to_check = components or all_components
        
        if check_type == "basic":
            components_to_check = ["system", "memory", "cpu", "services"]
        elif check_type == "all":
            components_to_check = all_components
            
        # Perform health checks for each component
        for component in components_to_check:
            try:
                if component == "system":
                    health_results["components"][component] = await _check_system_health()
                elif component == "memory":
                    health_results["components"][component] = await _check_memory_health()
                elif component == "cpu":
                    health_results["components"][component] = await _check_cpu_health()
                elif component == "disk":
                    health_results["components"][component] = await _check_disk_health()
                elif component == "network":
                    health_results["components"][component] = await _check_network_health()
                elif component == "services":
                    health_results["components"][component] = await _check_services_health()
                elif component == "embeddings":
                    health_results["components"][component] = await _check_embeddings_health()
                elif component == "vector_stores":
                    health_results["components"][component] = await _check_vector_stores_health()
                else:
                    health_results["components"][component] = {
                        "status": "unknown",
                        "message": f"Unknown component: {component}"
                    }
                    
            except Exception as e:
                health_results["components"][component] = {
                    "status": "error",
                    "error": str(e),
                    "message": f"Failed to check {component} health"
                }
                
        # Determine overall health status
        component_statuses = [comp.get("status", "unknown") for comp in health_results["components"].values()]
        
        if "critical" in component_statuses:
            health_results["overall_status"] = "critical"
        elif "warning" in component_statuses:
            health_results["overall_status"] = "warning"
        elif "error" in component_statuses:
            health_results["overall_status"] = "degraded"
        
        # Add performance metrics if requested
        if include_metrics:
            health_results["performance_metrics"] = await _get_performance_metrics()
            
        # Add health score
        healthy_count = sum(1 for status in component_statuses if status == "healthy")
        total_count = len(component_statuses)
        health_results["health_score"] = (healthy_count / total_count * 100) if total_count > 0 else 0
        
        # Store metrics
        METRICS_STORAGE["system_metrics"].append({
            "timestamp": timestamp.isoformat(),
            "health_score": health_results["health_score"],
            "overall_status": health_results["overall_status"]
        })
        
        # Keep only last 100 metrics
        METRICS_STORAGE["system_metrics"] = METRICS_STORAGE["system_metrics"][-100:]
        
        return {
            "success": True,
            "health_check": health_results,
            "recommendations": await _generate_health_recommendations(health_results)
        }
        
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return {
            "success": False,
            "error": str(e),
            "timestamp": datetime.now().isoformat()
        }


async def get_performance_metrics(
    metric_types: Optional[List[str]] = None,
    time_range: str = "1h",
    include_history: bool = True
) -> Dict[str, Any]:
    """
    Get system performance metrics and statistics.
    
    Args:
        metric_types: Types of metrics to retrieve
        time_range: Time range for historical metrics (1h, 6h, 24h, 7d)
        include_history: Include historical metrics data
        
    Returns:
        Dict containing performance metrics
    """
    try:
        timestamp = datetime.now()
        
        # Default metric types
        if not metric_types:
            metric_types = ["cpu", "memory", "disk", "network", "system"]
            
        metrics = {
            "timestamp": timestamp.isoformat(),
            "time_range": time_range,
            "current_metrics": {},
            "summary": {}
        }
        
        # Collect current metrics
        for metric_type in metric_types:
            if metric_type == "cpu":
                metrics["current_metrics"]["cpu"] = {
                    "usage_percent": psutil.cpu_percent(interval=1),
                    "count": psutil.cpu_count(),
                    "frequency": psutil.cpu_freq()._asdict() if psutil.cpu_freq() else None,
                    "load_average": psutil.getloadavg() if hasattr(psutil, 'getloadavg') else None
                }
            elif metric_type == "memory":
                memory = psutil.virtual_memory()
                metrics["current_metrics"]["memory"] = {
                    "total_gb": round(memory.total / (1024**3), 2),
                    "available_gb": round(memory.available / (1024**3), 2),
                    "used_gb": round(memory.used / (1024**3), 2),
                    "usage_percent": memory.percent,
                    "free_gb": round(memory.free / (1024**3), 2)
                }
            elif metric_type == "disk":
                disk_usage = psutil.disk_usage('/')
                metrics["current_metrics"]["disk"] = {
                    "total_gb": round(disk_usage.total / (1024**3), 2),
                    "used_gb": round(disk_usage.used / (1024**3), 2),
                    "free_gb": round(disk_usage.free / (1024**3), 2),
                    "usage_percent": round((disk_usage.used / disk_usage.total) * 100, 2)
                }
            elif metric_type == "network":
                network_stats = psutil.net_io_counters()
                metrics["current_metrics"]["network"] = {
                    "bytes_sent": network_stats.bytes_sent,
                    "bytes_recv": network_stats.bytes_recv,
                    "packets_sent": network_stats.packets_sent,
                    "packets_recv": network_stats.packets_recv
                }
            elif metric_type == "system":
                metrics["current_metrics"]["system"] = {
                    "boot_time": datetime.fromtimestamp(psutil.boot_time()).isoformat(),
                    "uptime_hours": round((time.time() - psutil.boot_time()) / 3600, 2),
                    "process_count": len(psutil.pids())
                }
                
        # Add historical metrics if requested
        if include_history:
            metrics["historical_metrics"] = METRICS_STORAGE["performance_metrics"][-50:]  # Last 50 entries
            
        # Generate summary statistics
        metrics["summary"] = {
            "metrics_collected": len(metric_types),
            "collection_time": timestamp.isoformat(),
            "system_load": "normal"  # Simple classification
        }
        
        # Store current metrics for history
        METRICS_STORAGE["performance_metrics"].append({
            "timestamp": timestamp.isoformat(),
            "metrics": metrics["current_metrics"]
        })
        
        # Keep only last 100 performance metrics
        METRICS_STORAGE["performance_metrics"] = METRICS_STORAGE["performance_metrics"][-100:]
        
        return {
            "success": True,
            "performance_metrics": metrics
        }
        
    except Exception as e:
        logger.error(f"Failed to get performance metrics: {e}")
        return {
            "success": False,
            "error": str(e),
            "timestamp": datetime.now().isoformat()
        }


async def monitor_services(
    services: Optional[List[str]] = None,
    check_interval: int = 30
) -> Dict[str, Any]:
    """
    Monitor specific services and their health status.
    
    Args:
        services: List of services to monitor
        check_interval: Interval between checks in seconds
        
    Returns:
        Dict containing service monitoring results
    """
    try:
        timestamp = datetime.now()
        
        # Default services to monitor
        if not services:
            services = [
                "embedding_service",
                "vector_store",
                "ipfs_node",
                "mcp_server",
                "cache_service"
            ]
            
        service_statuses = {}
        
        for service in services:
            try:
                status = await _check_service_status(service)
                service_statuses[service] = status
                
                # Update service health storage
                METRICS_STORAGE["service_health"][service] = {
                    "last_check": timestamp.isoformat(),
                    "status": status["status"],
                    "response_time": status.get("response_time", 0)
                }
                
            except Exception as e:
                service_statuses[service] = {
                    "status": "error",
                    "error": str(e),
                    "last_check": timestamp.isoformat()
                }
                
        # Calculate overall service health
        healthy_services = sum(1 for s in service_statuses.values() if s.get("status") == "healthy")
        total_services = len(service_statuses)
        service_health_score = (healthy_services / total_services * 100) if total_services > 0 else 0
        
        return {
            "success": True,
            "monitoring_results": {
                "timestamp": timestamp.isoformat(),
                "services_monitored": len(services),
                "service_statuses": service_statuses,
                "service_health_score": round(service_health_score, 2),
                "check_interval": check_interval,
                "next_check": (timestamp + timedelta(seconds=check_interval)).isoformat()
            }
        }
        
    except Exception as e:
        logger.error(f"Service monitoring failed: {e}")
        return {
            "success": False,
            "error": str(e),
            "timestamp": datetime.now().isoformat()
        }


async def generate_monitoring_report(
    report_type: str = "summary",
    time_period: str = "24h"
) -> Dict[str, Any]:
    """
    Generate comprehensive monitoring reports.
    
    Args:
        report_type: Type of report (summary, detailed, performance, alerts)
        time_period: Time period for the report (1h, 6h, 24h, 7d)
        
    Returns:
        Dict containing monitoring report
    """
    try:
        timestamp = datetime.now()
        
        # Calculate time range
        if time_period == "1h":
            start_time = timestamp - timedelta(hours=1)
        elif time_period == "6h":
            start_time = timestamp - timedelta(hours=6)
        elif time_period == "24h":
            start_time = timestamp - timedelta(hours=24)
        elif time_period == "7d":
            start_time = timestamp - timedelta(days=7)
        else:
            start_time = timestamp - timedelta(hours=24)
            
        report = {
            "report_type": report_type,
            "time_period": time_period,
            "generated_at": timestamp.isoformat(),
            "start_time": start_time.isoformat(),
            "end_time": timestamp.isoformat()
        }
        
        if report_type in ["summary", "detailed"]:
            # System health summary
            recent_metrics = [m for m in METRICS_STORAGE["system_metrics"] 
                            if datetime.fromisoformat(m["timestamp"]) >= start_time]
            
            if recent_metrics:
                avg_health_score = sum(m["health_score"] for m in recent_metrics) / len(recent_metrics)
                report["health_summary"] = {
                    "average_health_score": round(avg_health_score, 2),
                    "total_checks": len(recent_metrics),
                    "current_status": recent_metrics[-1]["overall_status"] if recent_metrics else "unknown"
                }
            else:
                report["health_summary"] = {
                    "message": "No health metrics available for the specified time period"
                }
                
        if report_type in ["performance", "detailed"]:
            # Performance summary
            recent_perf = [m for m in METRICS_STORAGE["performance_metrics"]
                          if datetime.fromisoformat(m["timestamp"]) >= start_time]
            
            if recent_perf:
                report["performance_summary"] = {
                    "metrics_collected": len(recent_perf),
                    "latest_cpu_usage": recent_perf[-1]["metrics"].get("cpu", {}).get("usage_percent", 0),
                    "latest_memory_usage": recent_perf[-1]["metrics"].get("memory", {}).get("usage_percent", 0)
                }
            else:
                report["performance_summary"] = {
                    "message": "No performance metrics available for the specified time period"
                }
                
        if report_type in ["alerts", "detailed"]:
            # Alerts summary
            recent_alerts = [a for a in METRICS_STORAGE["alerts"]
                           if datetime.fromisoformat(a.get("timestamp", timestamp.isoformat())) >= start_time]
            
            report["alerts_summary"] = {
                "total_alerts": len(recent_alerts),
                "critical_alerts": len([a for a in recent_alerts if a.get("severity") == "critical"]),
                "warning_alerts": len([a for a in recent_alerts if a.get("severity") == "warning"]),
                "recent_alerts": recent_alerts[-5:]  # Last 5 alerts
            }
            
        # Service health summary
        report["service_health_summary"] = {
            "services_monitored": len(METRICS_STORAGE["service_health"]),
            "healthy_services": len([s for s in METRICS_STORAGE["service_health"].values() 
                                   if s.get("status") == "healthy"]),
            "service_details": METRICS_STORAGE["service_health"]
        }
        
        return {
            "success": True,
            "monitoring_report": report
        }
        
    except Exception as e:
        logger.error(f"Failed to generate monitoring report: {e}")
        return {
            "success": False,
            "error": str(e),
            "timestamp": datetime.now().isoformat()
        }

