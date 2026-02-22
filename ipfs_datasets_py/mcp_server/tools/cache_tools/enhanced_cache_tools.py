# ipfs_datasets_py/mcp_server/tools/cache_tools/enhanced_cache_tools.py
"""
Enhanced cache management and optimization tools (thin MCP wrapper).

Business logic (CacheType, CacheStrategy, CacheEntry, CacheStats, MockCacheService)
lives in ipfs_datasets_py.caching.cache_engine.

MCP standalone functions below delegate all work to MockCacheService.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

# Import engine from core package (re-export for backward compat)
from ipfs_datasets_py.caching.cache_engine import (  # noqa: F401
    CacheType,
    CacheStrategy,
    CacheEntry,
    CacheStats,
    MockCacheService,
)

logger = logging.getLogger(__name__)

_DEFAULT_CACHE_SERVICE = MockCacheService()


async def get_cache_stats(
    cache_type: str = "all",
    include_history: bool = False,
    include_details: bool = True,
    format: str = "json",
) -> Dict[str, Any]:
    """Get cache statistics and performance metrics."""
    stats = await _DEFAULT_CACHE_SERVICE.get_cache_stats(CacheType(cache_type))
    result: Dict[str, Any] = {"cache_stats": stats, "timestamp": datetime.now().isoformat()}
    if include_details:
        result["analysis"] = {
            "efficiency_score": 85.2,
            "optimization_potential": "medium",
            "recommended_actions": [
                "Consider increasing TTL for frequently accessed items",
                "Monitor memory usage during peak hours",
            ],
        }
    if include_history:
        result["historical_trends"] = {
            "hit_rate_trend": "improving",
            "memory_usage_trend": "stable",
            "last_7_days": {"average_hit_rate": 0.83, "peak_memory_usage": 28.5},
        }
    if format == "summary":
        result = {
            "cache_health": "good",
            "hit_rate": stats["stats"]["hit_rate"],
            "memory_usage": f"{stats['stats']['memory_usage_percent']:.1f}%",
            "total_entries": stats["stats"]["total_entries"],
        }
    return result


async def manage_cache(
    action: str,
    cache_type: str = "all",
    confirm_clear: bool = False,
    configuration: Optional[Dict[str, Any]] = None,
    **_kwargs: Any,
) -> Dict[str, Any]:
    """Execute a cache management operation (clear / configure / warm_up / optimize / analyze)."""
    ct = CacheType(cache_type)
    if action == "clear":
        result = await _DEFAULT_CACHE_SERVICE.clear_cache(ct, confirm_clear)
        return {"action": "clear", "success": True, **result}
    if action in ("configure", "warm_up", "optimize", "analyze"):
        result = await _DEFAULT_CACHE_SERVICE.manage_cache(action, ct, configuration or {})
        return {"success": True, **result}
    raise ValueError(f"Unknown action: {action!r}")


async def monitor_cache(
    time_window: str = "1h",
    metrics: Optional[List[str]] = None,
    alert_thresholds: Optional[Dict[str, Any]] = None,
    include_predictions: bool = False,
    cache_types: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Monitor cache performance, health metrics, and usage patterns."""
    metrics = metrics or ["hit_rate", "latency", "memory_usage"]
    alert_thresholds = alert_thresholds or {}
    cache_types = cache_types or ["embedding", "search"]

    data = await _DEFAULT_CACHE_SERVICE.monitor_cache(time_window, metrics)

    alerts: List[Dict[str, Any]] = []
    if "hit_rate" in data.get("metrics", {}):
        hit_rate = data["metrics"]["hit_rate"]["current"]
        min_thr = alert_thresholds.get("hit_rate_min", 0.7)
        if hit_rate < min_thr:
            alerts.append({"type": "warning", "metric": "hit_rate", "current_value": hit_rate, "threshold": min_thr})
    if "memory_usage" in data.get("metrics", {}):
        mem_pct = data["metrics"]["memory_usage"]["utilization_percent"]
        max_thr = alert_thresholds.get("memory_usage_max_percent", 90.0)
        if mem_pct > max_thr:
            alerts.append({"type": "critical", "metric": "memory_usage", "current_value": mem_pct, "threshold": max_thr})

    data["alerts"] = alerts
    data["alert_count"] = len(alerts)
    data["cache_types_monitored"] = cache_types
    data["monitoring_config"] = {"time_window": time_window, "metrics_tracked": metrics}
    if include_predictions:
        data["predictions"] = {"next_hour_hit_rate": 0.87, "memory_usage_trend": "stable"}
    return data


# ---------------------------------------------------------------------------
# Backward-compat shims (thin wrappers that expose the old class interface)
# ---------------------------------------------------------------------------

class EnhancedCacheStatsTool:
    """Backward-compat shim for EnhancedCacheStatsTool."""
    name = "enhanced_cache_stats"

    async def execute(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        return await get_cache_stats(**parameters)


class EnhancedCacheManagementTool:
    """Backward-compat shim for EnhancedCacheManagementTool."""
    name = "enhanced_cache_management"

    async def execute(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        return await manage_cache(**parameters)


class EnhancedCacheMonitoringTool:
    """Backward-compat shim for EnhancedCacheMonitoringTool."""
    name = "enhanced_cache_monitoring"

    async def execute(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        return await monitor_cache(**parameters)


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
    "manage_cache",
    "monitor_cache",
]
