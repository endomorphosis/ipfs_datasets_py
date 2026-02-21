# ipfs_datasets_py/mcp_server/tools/admin_tools/enhanced_admin_tools.py
"""
Enhanced admin tools — standalone async MCP functions.

Business logic (ServiceStatus, MaintenanceMode, SystemInfo, MockAdminService)
lives in ipfs_datasets_py.admin.admin_engine.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

# Import engine from core package (re-export for backward compat)
from ipfs_datasets_py.admin.admin_engine import (  # noqa: F401
    MaintenanceMode,
    MockAdminService,
    ServiceStatus,
    SystemInfo,
)

logger = logging.getLogger(__name__)

_DEFAULT_ADMIN_SERVICE = MockAdminService()


async def get_system_status(
    include_details: bool = True,
    include_services: bool = True,
    include_resources: bool = True,
    format: str = "json",
) -> Dict[str, Any]:
    """Get comprehensive system status."""
    status = await _DEFAULT_ADMIN_SERVICE.get_system_status()
    result: Dict[str, Any] = {
        "system_status": "operational",
        "timestamp": datetime.now().isoformat(),
        "health_status": status["health_status"],
    }
    if include_details:
        result["system_info"] = status["system_info"]
    if include_services:
        result["services"] = status["services"]
        result["maintenance_mode"] = status["maintenance_mode"]
    if include_resources:
        result["resource_usage"] = status["resource_usage"]
    if format == "summary":
        result = {
            "status": "operational",
            "health": status["health_status"],
            "services_running": sum(1 for s in status["services"].values() if s == "running"),
            "total_services": len(status["services"]),
            "cpu_usage": status["resource_usage"]["cpu_percent"],
            "memory_usage": status["resource_usage"]["memory_percent"],
        }
    elif format == "detailed":
        result["diagnostics"] = {
            "last_restart": "2024-01-15T10:30:00Z",
            "error_count_24h": 5,
            "warning_count_24h": 12,
            "active_connections": 45,
            "queue_length": 3,
        }
    return result


async def manage_service(
    service_name: str,
    action: str,
    force: bool = False,
    timeout_seconds: int = 30,
) -> Dict[str, Any]:
    """Manage system services (start/stop/restart/status)."""
    _ALL_SERVICES = ["ipfs_daemon", "vector_store", "cache_service", "monitoring_service"]
    if service_name == "all" and action in ("start", "stop", "restart"):
        results: List[Dict[str, Any]] = []
        for svc in _ALL_SERVICES:
            try:
                results.append(await _DEFAULT_ADMIN_SERVICE.manage_service(svc, action))
            except Exception as exc:
                results.append({"service_name": svc, "action": action, "error": str(exc), "success": False})
        return {
            "bulk_operation": True,
            "action": action,
            "total_services": len(results),
            "successful_operations": sum(1 for r in results if "error" not in r),
            "failed_operations": sum(1 for r in results if "error" in r),
            "results": results,
        }
    result = await _DEFAULT_ADMIN_SERVICE.manage_service(service_name, action)
    return {"single_operation": True, "success": True, "timeout_seconds": timeout_seconds, "force_applied": force, **result}


async def update_configuration(
    action: str,
    config_updates: Optional[Dict[str, Any]] = None,
    create_backup: bool = True,
    validate_config: bool = True,
) -> Dict[str, Any]:
    """Get, update, validate, backup, or restore system configuration."""
    config_updates = config_updates or {}
    if action == "get":
        return {"action": "get", "configuration": _DEFAULT_ADMIN_SERVICE.configuration, "timestamp": datetime.now().isoformat()}
    if action == "update":
        if not config_updates:
            raise ValueError("No configuration updates provided")
        if validate_config:
            invalid = [k for k in config_updates if not k.replace(".", "").replace("_", "").isalnum()]
            if invalid:
                raise ValueError(f"Invalid configuration keys: {invalid}")
        result = await _DEFAULT_ADMIN_SERVICE.update_configuration(config_updates, create_backup)
        return {"action": "update", "validation_passed": validate_config, **result}
    if action == "validate":
        validation_results = []
        for key, value in config_updates.items():
            if "batch_size" in key and not isinstance(value, int):
                validation_results.append({"key": key, "error": "Must be an integer"})
            elif "timeout" in key and value < 1:
                validation_results.append({"key": key, "error": "Must be positive"})
            else:
                validation_results.append({"key": key, "status": "valid"})
        return {"action": "validate", "validation_results": validation_results, "is_valid": all("error" not in r for r in validation_results)}
    # backup / restore
    return {"action": action, "success": True, "message": f"Configuration {action} completed successfully", "timestamp": datetime.now().isoformat()}


async def cleanup_resources(
    cleanup_type: str = "basic",
    restart_services: bool = True,
    cleanup_temp_files: bool = True,
    cleanup_logs: bool = False,
    max_log_age_days: int = 30,
) -> Dict[str, Any]:
    """Clean up system resources."""
    result = await _DEFAULT_ADMIN_SERVICE.cleanup_resources(cleanup_type)
    result.update({
        "cleanup_options": {
            "restart_services": restart_services,
            "cleanup_temp_files": cleanup_temp_files,
            "cleanup_logs": cleanup_logs,
            "max_log_age_days": max_log_age_days,
        },
        "performance_impact": {
            "memory_freed_percent": (result["freed_memory_bytes"] / (1024 ** 3)) / 8.0 * 100,
            "disk_freed_percent": result.get("disk_space_freed_mb", 0) / 10000 * 100,
            "estimated_performance_improvement": "5-10%" if cleanup_type == "full" else "2-5%",
        },
        "recommendations": [
            "Consider scheduling regular cleanup operations",
            "Monitor disk usage to prevent future issues",
            "Enable automatic cache cleanup" if cleanup_type == "full" else "Run full cleanup monthly",
        ],
    })
    return result


# Backward-compatible class shims (thin wrappers around the functions above)
class EnhancedSystemStatusTool:
    """Backward-compatible shim."""
    async def execute(self, parameters: Dict[str, Any]) -> Dict[str, Any]:  # noqa: D102
        return await get_system_status(**{k: v for k, v in parameters.items() if k in ("include_details", "include_services", "include_resources", "format")})


class EnhancedServiceManagementTool:
    """Backward-compatible shim."""
    async def execute(self, parameters: Dict[str, Any]) -> Dict[str, Any]:  # noqa: D102
        return await manage_service(parameters["service_name"], parameters["action"], parameters.get("force", False), parameters.get("timeout_seconds", 30))


class EnhancedConfigurationTool:
    """Backward-compatible shim."""
    async def execute(self, parameters: Dict[str, Any]) -> Dict[str, Any]:  # noqa: D102
        return await update_configuration(parameters["action"], parameters.get("config_updates"), parameters.get("create_backup", True), parameters.get("validate_config", True))


class EnhancedResourceCleanupTool:
    """Backward-compatible shim."""
    async def execute(self, parameters: Dict[str, Any]) -> Dict[str, Any]:  # noqa: D102
        return await cleanup_resources(parameters.get("cleanup_type", "basic"), parameters.get("restart_services", True), parameters.get("cleanup_temp_files", True), parameters.get("cleanup_logs", False), parameters.get("max_log_age_days", 30))


__all__ = [
    "get_system_status",
    "manage_service",
    "update_configuration",
    "cleanup_resources",
    "EnhancedSystemStatusTool",
    "EnhancedServiceManagementTool",
    "EnhancedConfigurationTool",
    "EnhancedResourceCleanupTool",
    "ServiceStatus",
    "MaintenanceMode",
    "SystemInfo",
    "MockAdminService",
]

