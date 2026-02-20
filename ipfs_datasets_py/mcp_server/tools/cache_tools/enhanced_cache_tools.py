# ipfs_datasets_py/mcp_server/tools/cache_tools/enhanced_cache_tools.py
"""
Enhanced cache management and optimization tools (thin MCP wrapper).

Business logic (CacheType, CacheStrategy, CacheEntry, CacheStats, MockCacheService)
lives in ipfs_datasets_py.caching.cache_engine.

MCP tool classes below delegate all work to MockCacheService.
"""

import anyio
import json
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
from dataclasses import asdict

from ..tool_wrapper import EnhancedBaseMCPTool
from ...validators import EnhancedParameterValidator
from ...monitoring import EnhancedMetricsCollector

# Import engine from core package (re-export for backward compat)
from ipfs_datasets_py.caching.cache_engine import (  # noqa: F401
    CacheType,
    CacheStrategy,
    CacheEntry,
    CacheStats,
    MockCacheService,
)

logger = logging.getLogger(__name__)

class EnhancedCacheStatsTool(EnhancedBaseMCPTool):
    """Enhanced tool for retrieving cache statistics and performance metrics."""
    
    def __init__(self, cache_service=None, validator=None, metrics_collector=None):
        super().__init__(
            name="enhanced_cache_stats",
            description="Get comprehensive cache statistics, performance metrics, and health information.",
            category="cache",
            version="1.0.0",
            validator=validator or EnhancedParameterValidator(),
            metrics_collector=metrics_collector or EnhancedMetricsCollector()
        )
        
        self.cache_service = cache_service or MockCacheService()
        
        self.input_schema = {
            "type": "object",
            "properties": {
                "cache_type": {
                    "type": "string",
                    "description": "Type of cache to get stats for",
                    "enum": ["embedding", "search", "metadata", "computation", "all"],
                    "default": "all"
                },
                "include_history": {
                    "type": "boolean",
                    "description": "Include historical statistics",
                    "default": False
                },
                "include_details": {
                    "type": "boolean",
                    "description": "Include detailed cache analysis",
                    "default": True
                },
                "format": {
                    "type": "string",
                    "description": "Output format",
                    "enum": ["json", "summary", "detailed"],
                    "default": "json"
                }
            }
        }
    
    async def _execute_impl(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """Get cache statistics."""
        cache_type = CacheType(parameters.get("cache_type", "all"))
        include_history = parameters.get("include_history", False)
        include_details = parameters.get("include_details", True)
        output_format = parameters.get("format", "json")
        
        stats = await self.cache_service.get_cache_stats(cache_type)
        
        result = {
            "cache_stats": stats,
            "timestamp": datetime.now().isoformat()
        }
        
        # TODO EVEN MORE FUCKING MOCKS
        if include_details:
            result["analysis"] = {
                "efficiency_score": 85.2,
                "optimization_potential": "medium",
                "recommended_actions": [
                    "Consider increasing TTL for frequently accessed items",
                    "Monitor memory usage during peak hours",
                    "Review eviction strategy for better performance"
                ]
            }
        
        if include_history:
            result["historical_trends"] = {
                "hit_rate_trend": "improving",
                "memory_usage_trend": "stable",
                "performance_trend": "good",
                "last_7_days": {
                    "average_hit_rate": 0.83,
                    "peak_memory_usage": 28.5,
                    "average_latency_ms": 2.2
                }
            }
        
        if output_format == "summary":
            # Simplified summary
            result = {
                "cache_health": "good",
                "hit_rate": stats["stats"]["hit_rate"],
                "memory_usage": f"{stats['stats']['memory_usage_percent']:.1f}%",
                "total_entries": stats["stats"]["total_entries"],
                "recommendations": "Performance is good, no immediate action required"
            }
        
        return result

class EnhancedCacheManagementTool(EnhancedBaseMCPTool):
    """Enhanced tool for cache management operations."""
    
    def __init__(self, cache_service=None, validator=None, metrics_collector=None):
        super().__init__(
            name="enhanced_cache_management",
            description="Manage cache operations including clearing, configuration, warming, and optimization.",
            category="cache",
            version="1.0.0",
            validator=validator or EnhancedParameterValidator(),
            metrics_collector=metrics_collector or EnhancedMetricsCollector()
        )
        
        self.cache_service = cache_service or MockCacheService()
        
        self.input_schema = {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "description": "Cache management action",
                    "enum": ["clear", "configure", "warm_up", "optimize", "analyze"]
                },
                "cache_type": {
                    "type": "string",
                    "description": "Type of cache to manage",
                    "enum": ["embedding", "search", "metadata", "computation", "all"],
                    "default": "all"
                },
                "confirm_clear": {
                    "type": "boolean",
                    "description": "Confirmation for cache clear operation",
                    "default": False
                },
                "configuration": {
                    "type": "object",
                    "description": "Cache configuration settings",
                    "properties": {
                        "max_size_bytes": {"type": "integer", "minimum": 1048576},  # 1MB minimum
                        "default_ttl_seconds": {"type": "integer", "minimum": 60, "maximum": 86400},
                        "eviction_strategy": {"type": "string", "enum": ["lru", "lfu", "fifo", "ttl", "adaptive"]},
                        "compression_enabled": {"type": "boolean"}
                    }
                },
                "warm_strategy": {
                    "type": "string",
                    "description": "Cache warming strategy",
                    "enum": ["frequent_queries", "recent_data", "predictive", "all"],
                    "default": "frequent_queries"
                },
                "max_entries": {
                    "type": "integer",
                    "description": "Maximum entries to warm or process",
                    "minimum": 1,
                    "maximum": 100000,
                    "default": 10000
                }
            },
            "required": ["action"]
        }
    
    async def _execute_impl(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """Execute cache management operation."""
        action = parameters["action"]
        cache_type = CacheType(parameters.get("cache_type", "all"))
        
        if action == "clear":
            confirm_clear = parameters.get("confirm_clear", False)
            result = await self.cache_service.clear_cache(cache_type, confirm_clear)
            
            return {
                "action": "clear",
                "success": True,
                **result
            }
        
        elif action in ["configure", "warm_up", "optimize", "analyze"]:
            config = parameters.get("configuration", {})
            result = await self.cache_service.manage_cache(action, cache_type, config)
            
            return {
                "success": True,
                **result
            }
        
        else:
            raise ValueError(f"Unknown action: {action}")

class EnhancedCacheMonitoringTool(EnhancedBaseMCPTool):
    """Enhanced tool for real-time cache monitoring and alerting."""
    
    def __init__(self, cache_service=None, validator=None, metrics_collector=None):
        super().__init__(
            name="enhanced_cache_monitoring",
            description="Monitor cache performance, health metrics, and usage patterns with real-time alerting.",
            category="cache",
            version="1.0.0",
            validator=validator or EnhancedParameterValidator(),
            metrics_collector=metrics_collector or EnhancedMetricsCollector()
        )
        
        self.cache_service = cache_service or MockCacheService()
        
        self.input_schema = {
            "type": "object",
            "properties": {
                "time_window": {
                    "type": "string",
                    "description": "Time window for monitoring data",
                    "enum": ["5m", "15m", "1h", "6h", "24h", "7d"],
                    "default": "1h"
                },
                "metrics": {
                    "type": "array",
                    "description": "Specific metrics to monitor",
                    "items": {
                        "type": "string",
                        "enum": ["hit_rate", "miss_rate", "latency", "memory_usage", "throughput", "eviction_rate"]
                    },
                    "default": ["hit_rate", "latency", "memory_usage"]
                },
                "alert_thresholds": {
                    "type": "object",
                    "description": "Custom alert thresholds",
                    "properties": {
                        "hit_rate_min": {"type": "number", "minimum": 0, "maximum": 1},
                        "latency_max_ms": {"type": "number", "minimum": 0},
                        "memory_usage_max_percent": {"type": "number", "minimum": 0, "maximum": 100}
                    }
                },
                "include_predictions": {
                    "type": "boolean",
                    "description": "Include performance predictions",
                    "default": False
                },
                "cache_types": {
                    "type": "array",
                    "description": "Cache types to monitor",
                    "items": {
                        "type": "string",
                        "enum": ["embedding", "search", "metadata", "computation"]
                    },
                    "default": ["embedding", "search"]
                }
            }
        }
    
    async def _execute_impl(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """Monitor cache performance."""
        time_window = parameters.get("time_window", "1h")
        metrics = parameters.get("metrics", ["hit_rate", "latency", "memory_usage"])
        alert_thresholds = parameters.get("alert_thresholds", {})
        include_predictions = parameters.get("include_predictions", False)
        cache_types = parameters.get("cache_types", ["embedding", "search"])
        
        monitoring_data = await self.cache_service.monitor_cache(time_window, metrics)
        
        # Check alert thresholds
        alerts = []
        if "hit_rate" in monitoring_data["metrics"]:
            hit_rate = monitoring_data["metrics"]["hit_rate"]["current"]
            min_threshold = alert_thresholds.get("hit_rate_min", 0.7)
            if hit_rate < min_threshold:
                alerts.append({
                    "type": "warning",
                    "metric": "hit_rate",
                    "current_value": hit_rate,
                    "threshold": min_threshold,
                    "message": f"Cache hit rate ({hit_rate:.2%}) below threshold ({min_threshold:.2%})"
                })
        
        if "memory_usage" in monitoring_data["metrics"]:
            memory_percent = monitoring_data["metrics"]["memory_usage"]["utilization_percent"]
            max_threshold = alert_thresholds.get("memory_usage_max_percent", 90.0)
            if memory_percent > max_threshold:
                alerts.append({
                    "type": "critical",
                    "metric": "memory_usage",
                    "current_value": memory_percent,
                    "threshold": max_threshold,
                    "message": f"Cache memory usage ({memory_percent:.1f}%) exceeds threshold ({max_threshold:.1f}%)"
                })
        
        monitoring_data["alerts"] = alerts
        monitoring_data["alert_count"] = len(alerts)
        
        # Add cache type specific data
        monitoring_data["cache_types_monitored"] = cache_types
        monitoring_data["monitoring_config"] = {
            "time_window": time_window,
            "metrics_tracked": metrics,
            "alert_thresholds": alert_thresholds
        }
        
        if include_predictions:
            monitoring_data["predictions"] = {
                "next_hour_hit_rate": 0.87,
                "memory_usage_trend": "stable",
                "recommended_actions": [
                    "Monitor hit rate closely",
                    "Consider cache warming for peak hours"
                ],
                "capacity_forecast": {
                    "days_until_full": 45,
                    "growth_rate_percent": 2.3
                }
            }
        
        return monitoring_data


# Module-level helpers for compatibility with legacy tests/usage
_DEFAULT_CACHE_SERVICE = MockCacheService()


async def get_cache_stats(cache_type: str = "all") -> Dict[str, Any]:
    """Get cache statistics using the default cache service."""
    return await _DEFAULT_CACHE_SERVICE.get_cache_stats(CacheType(cache_type))


async def clear_cache(cache_type: str = "all", confirm_clear: bool = True) -> Dict[str, Any]:
    """Clear cache entries using the default cache service."""
    return await _DEFAULT_CACHE_SERVICE.clear_cache(CacheType(cache_type), confirm_clear)


async def monitor_cache(
    time_window: str = "1h",
    metrics: Optional[List[str]] = None
) -> Dict[str, Any]:
    """Monitor cache performance using the default cache service."""
    metrics = metrics or ["hit_rate", "latency", "memory_usage"]
    return await _DEFAULT_CACHE_SERVICE.monitor_cache(time_window, metrics)

# Export the enhanced tools
__all__ = [
    "EnhancedCacheStatsTool",
    "EnhancedCacheManagementTool",
    "EnhancedCacheMonitoringTool",
    "CacheType",
    "CacheStrategy",
    "CacheEntry",
    "CacheStats",
    "MockCacheService",
    "get_cache_stats",
    "clear_cache",
    "monitor_cache"
]
