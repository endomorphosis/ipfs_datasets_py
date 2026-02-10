# ipfs_datasets_py/mcp_server/tools/monitoring_tools/monitoring_tools.py
"""
System monitoring and health check tools.
Migrated from a legacy tooling codebase.
"""

import logging
import anyio
import psutil
import time
from typing import Dict, Any, List, Optional, Union
from datetime import datetime, timedelta
import json

logger = logging.getLogger(__name__)

# Global metrics storage
METRICS_STORAGE = {
    "system_metrics": [],
    "performance_metrics": [],
    "service_health": {},
    "alerts": []
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


# Helper functions for health checks

async def _check_system_health() -> Dict[str, Any]:
    """Check overall system health."""
    try:
        uptime_hours = (time.time() - psutil.boot_time()) / 3600
        
        status = "healthy"
        if uptime_hours < 0.1:  # Less than 6 minutes
            status = "warning"
            
        return {
            "status": status,
            "uptime_hours": round(uptime_hours, 2),
            "boot_time": datetime.fromtimestamp(psutil.boot_time()).isoformat(),
            "process_count": len(psutil.pids())
        }
    except Exception as e:
        return {"status": "error", "error": str(e)}


async def _check_memory_health() -> Dict[str, Any]:
    """Check memory health."""
    try:
        memory = psutil.virtual_memory()
        
        status = "healthy"
        if memory.percent > 90:
            status = "critical"
        elif memory.percent > 80:
            status = "warning"
            
        return {
            "status": status,
            "usage_percent": memory.percent,
            "available_gb": round(memory.available / (1024**3), 2),
            "total_gb": round(memory.total / (1024**3), 2)
        }
    except Exception as e:
        return {"status": "error", "error": str(e)}


async def _check_cpu_health() -> Dict[str, Any]:
    """Check CPU health."""
    try:
        cpu_percent = psutil.cpu_percent(interval=1)
        
        status = "healthy"
        if cpu_percent > 95:
            status = "critical"
        elif cpu_percent > 85:
            status = "warning"
            
        return {
            "status": status,
            "usage_percent": cpu_percent,
            "count": psutil.cpu_count(),
            "load_average": psutil.getloadavg() if hasattr(psutil, 'getloadavg') else None
        }
    except Exception as e:
        return {"status": "error", "error": str(e)}


async def _check_disk_health() -> Dict[str, Any]:
    """Check disk health."""
    try:
        disk_usage = psutil.disk_usage('/')
        usage_percent = (disk_usage.used / disk_usage.total) * 100
        
        status = "healthy"
        if usage_percent > 95:
            status = "critical"
        elif usage_percent > 85:
            status = "warning"
            
        return {
            "status": status,
            "usage_percent": round(usage_percent, 2),
            "free_gb": round(disk_usage.free / (1024**3), 2),
            "total_gb": round(disk_usage.total / (1024**3), 2)
        }
    except Exception as e:
        return {"status": "error", "error": str(e)}


async def _check_network_health() -> Dict[str, Any]:
    """Check network health."""
    try:
        # Basic network connectivity check
        network_stats = psutil.net_io_counters()
        
        return {
            "status": "healthy",
            "bytes_sent": network_stats.bytes_sent,
            "bytes_recv": network_stats.bytes_recv,
            "packets_sent": network_stats.packets_sent,
            "packets_recv": network_stats.packets_recv
        }
    except Exception as e:
        return {"status": "error", "error": str(e)}


async def _check_services_health() -> Dict[str, Any]:
    """Check health of key services."""
    try:
        # Mock service health checks
        services = {
            "mcp_server": "healthy",
            "embedding_service": "healthy",
            "vector_store": "warning",  # Simulate some issues
            "cache_service": "healthy"
        }
        
        healthy_count = sum(1 for status in services.values() if status == "healthy")
        total_count = len(services)
        
        overall_status = "healthy"
        if healthy_count < total_count * 0.5:
            overall_status = "critical"
        elif healthy_count < total_count:
            overall_status = "warning"
            
        return {
            "status": overall_status,
            "services": services,
            "healthy_services": healthy_count,
            "total_services": total_count
        }
    except Exception as e:
        return {"status": "error", "error": str(e)}


async def _check_embeddings_health() -> Dict[str, Any]:
    """Check embeddings service health."""
    try:
        # Mock embeddings service health
        return {
            "status": "healthy",
            "active_models": 3,
            "endpoints_available": 5,
            "last_embedding_time": datetime.now().isoformat(),
            "cache_hit_rate": 85.5
        }
    except Exception as e:
        return {"status": "error", "error": str(e)}


async def _check_vector_stores_health() -> Dict[str, Any]:
    """Check vector stores health."""
    try:
        # Mock vector stores health
        stores = {
            "faiss": {"status": "healthy", "indices": 8, "size_mb": 245},
            "qdrant": {"status": "healthy", "collections": 5, "vectors": 10000},
            "elasticsearch": {"status": "warning", "indices": 3, "health": "yellow"}
        }
        
        return {
            "status": "healthy",
            "stores": stores,
            "total_stores": len(stores),
            "healthy_stores": sum(1 for s in stores.values() if s["status"] == "healthy")
        }
    except Exception as e:
        return {"status": "error", "error": str(e)}


async def _check_service_status(service_name: str) -> Dict[str, Any]:
    """Check status of a specific service."""
    try:
        # Mock service status check
        start_time = time.time()
        await anyio.sleep(0.01)  # Simulate network delay
        response_time = (time.time() - start_time) * 1000  # ms
        
        # Simulate different service statuses
        if service_name == "vector_store":
            status = "warning"
            message = "High response times detected"
        elif service_name == "cache_service":
            status = "healthy"
            message = "Operating normally"
        else:
            status = "healthy"
            message = "Service operational"
            
        return {
            "status": status,
            "response_time": round(response_time, 2),
            "message": message,
            "last_check": datetime.now().isoformat()
        }
    except Exception as e:
        return {"status": "error", "error": str(e)}


async def _get_performance_metrics() -> Dict[str, Any]:
    """Get current performance metrics."""
    try:
        return {
            "cpu_usage": psutil.cpu_percent(interval=0.1),
            "memory_usage": psutil.virtual_memory().percent,
            "disk_usage": (psutil.disk_usage('/').used / psutil.disk_usage('/').total) * 100,
            "process_count": len(psutil.pids()),
            "network_connections": len(psutil.net_connections())
        }
    except Exception as e:
        return {"error": str(e)}


async def _generate_health_recommendations(health_results: Dict[str, Any]) -> List[str]:
    """Generate health recommendations based on results."""
    recommendations = []
    
    try:
        components = health_results.get("components", {})
        
        for component, data in components.items():
            status = data.get("status", "unknown")
            
            if status == "critical":
                if component == "memory" and data.get("usage_percent", 0) > 90:
                    recommendations.append("Critical: Memory usage above 90%. Consider restarting services or adding more RAM.")
                elif component == "cpu" and data.get("usage_percent", 0) > 95:
                    recommendations.append("Critical: CPU usage above 95%. Check for runaway processes.")
                elif component == "disk" and data.get("usage_percent", 0) > 95:
                    recommendations.append("Critical: Disk usage above 95%. Clean up disk space immediately.")
                    
            elif status == "warning":
                if component == "memory" and data.get("usage_percent", 0) > 80:
                    recommendations.append("Warning: Memory usage above 80%. Monitor closely.")
                elif component == "cpu" and data.get("usage_percent", 0) > 85:
                    recommendations.append("Warning: CPU usage above 85%. Consider load balancing.")
                    
        if health_results.get("health_score", 100) < 80:
            recommendations.append("Overall system health below 80%. Review all component statuses.")
            
        if not recommendations:
            recommendations.append("System appears healthy. Continue regular monitoring.")
            
    except Exception as e:
        recommendations.append(f"Error generating recommendations: {str(e)}")
        
    return recommendations
