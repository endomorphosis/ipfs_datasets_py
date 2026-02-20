# ipfs_datasets_py/mcp_server/tools/admin_tools/enhanced_admin_tools.py
"""
Enhanced admin tools (thin MCP wrapper).

Business logic (ServiceStatus, MaintenanceMode, SystemInfo, MockAdminService)
lives in ipfs_datasets_py.admin.admin_engine.

MCP tool classes below delegate to MockAdminService.
"""

import logging
from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta
from dataclasses import asdict

from ..tool_wrapper import EnhancedBaseMCPTool
from ...validators import EnhancedParameterValidator
from ...monitoring import EnhancedMetricsCollector

# Import engine from core package (re-export for backward compat)
from ipfs_datasets_py.admin.admin_engine import (  # noqa: F401
    ServiceStatus,
    MaintenanceMode,
    SystemInfo,
    MockAdminService,
)

logger = logging.getLogger(__name__)

class EnhancedSystemStatusTool(EnhancedBaseMCPTool):
    """Enhanced tool for comprehensive system status monitoring."""
    
    def __init__(self, admin_service=None, validator=None, metrics_collector=None):
        super().__init__(
            name="enhanced_system_status",
            description="Get comprehensive system status including services, resources, and health metrics.",
            category="admin",
            version="1.0.0",
            validator=validator or EnhancedParameterValidator(),
            metrics_collector=metrics_collector or EnhancedMetricsCollector()
        )
        
        self.admin_service = admin_service or MockAdminService()
        
        self.input_schema = {
            "type": "object",
            "properties": {
                "include_details": {
                    "type": "boolean",
                    "description": "Include detailed system information",
                    "default": True
                },
                "include_services": {
                    "type": "boolean",
                    "description": "Include service status information",
                    "default": True
                },
                "include_resources": {
                    "type": "boolean", 
                    "description": "Include resource usage metrics",
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
        """Get comprehensive system status."""
        include_details = parameters.get("include_details", True)
        include_services = parameters.get("include_services", True)
        include_resources = parameters.get("include_resources", True)
        output_format = parameters.get("format", "json")
        
        status = await self.admin_service.get_system_status()
        
        result = {
            "system_status": "operational",
            "timestamp": datetime.now().isoformat(),
            "health_status": status["health_status"]
        }
        
        if include_details:
            result["system_info"] = status["system_info"]
        
        if include_services:
            result["services"] = status["services"]
            result["maintenance_mode"] = status["maintenance_mode"]
        
        if include_resources:
            result["resource_usage"] = status["resource_usage"]
        
        if output_format == "summary":
            # Simplified summary format
            result = {
                "status": "operational",
                "health": status["health_status"],
                "services_running": sum(1 for s in status["services"].values() if s == "running"),
                "total_services": len(status["services"]),
                "cpu_usage": status["resource_usage"]["cpu_percent"],
                "memory_usage": status["resource_usage"]["memory_percent"]
            }
        elif output_format == "detailed":
            # Add extra diagnostic information
            result["diagnostics"] = {
                "last_restart": "2024-01-15T10:30:00Z",
                "error_count_24h": 5,
                "warning_count_24h": 12,
                "active_connections": 45,
                "queue_length": 3
            }
        
        return result

class EnhancedServiceManagementTool(EnhancedBaseMCPTool):
    """Enhanced tool for managing system services."""
    
    def __init__(self, admin_service=None, validator=None, metrics_collector=None):
        super().__init__(
            name="enhanced_service_management",
            description="Start, stop, restart, and monitor system services with advanced controls.",
            category="admin",
            version="1.0.0",
            validator=validator or EnhancedParameterValidator(),
            metrics_collector=metrics_collector or EnhancedMetricsCollector()
        )
        
        self.admin_service = admin_service or MockAdminService()
        
        self.input_schema = {
            "type": "object",
            "properties": {
                "service_name": {
                    "type": "string",
                    "description": "Name of the service to manage",
                    "enum": ["ipfs_daemon", "vector_store", "cache_service", "monitoring_service", "workflow_engine", "all"]
                },
                "action": {
                    "type": "string",
                    "description": "Action to perform on the service",
                    "enum": ["start", "stop", "restart", "status", "enable", "disable"]
                },
                "force": {
                    "type": "boolean",
                    "description": "Force the action even if risky",
                    "default": False
                },
                "timeout_seconds": {
                    "type": "integer",
                    "description": "Timeout for the operation",
                    "minimum": 5,
                    "maximum": 300,
                    "default": 30
                }
            },
            "required": ["service_name", "action"]
        }
    
    async def _execute_impl(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """Manage system services."""
        service_name = parameters["service_name"]
        action = parameters["action"]
        force = parameters.get("force", False)
        timeout_seconds = parameters.get("timeout_seconds", 30)
        
        if service_name == "all" and action in ["start", "stop", "restart"]:
            # Handle bulk operations
            results = []
            for svc_name in ["ipfs_daemon", "vector_store", "cache_service", "monitoring_service"]:
                try:
                    result = await self.admin_service.manage_service(svc_name, action)
                    results.append(result)
                except Exception as e:
                    results.append({
                        "service_name": svc_name,
                        "action": action,
                        "error": str(e),
                        "success": False
                    })
            
            return {
                "bulk_operation": True,
                "action": action,
                "total_services": len(results),
                "successful_operations": sum(1 for r in results if "error" not in r),
                "failed_operations": sum(1 for r in results if "error" in r),
                "results": results
            }
        else:
            # Handle single service operation
            result = await self.admin_service.manage_service(service_name, action)
            
            return {
                "single_operation": True,
                "success": True,
                "timeout_seconds": timeout_seconds,
                "force_applied": force,
                **result
            }

class EnhancedConfigurationTool(EnhancedBaseMCPTool):
    """Enhanced tool for system configuration management."""
    
    def __init__(self, admin_service=None, validator=None, metrics_collector=None):
        super().__init__(
            name="enhanced_configuration",
            description="Update and manage system configuration with validation and backup.",
            category="admin",
            version="1.0.0",
            validator=validator or EnhancedParameterValidator(),
            metrics_collector=metrics_collector or EnhancedMetricsCollector()
        )
        
        self.admin_service = admin_service or MockAdminService()
        
        self.input_schema = {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "description": "Configuration action",
                    "enum": ["get", "update", "validate", "backup", "restore"]
                },
                "config_updates": {
                    "type": "object",
                    "description": "Configuration updates in dot notation (e.g., 'embedding.batch_size': 64)",
                    "additionalProperties": True
                },
                "create_backup": {
                    "type": "boolean",
                    "description": "Create backup before updating",
                    "default": True
                },
                "validate_config": {
                    "type": "boolean",
                    "description": "Validate configuration before applying",
                    "default": True
                },
                "backup_location": {
                    "type": "string",
                    "description": "Backup file location (for restore action)"
                }
            },
            "required": ["action"]
        }
    
    async def _execute_impl(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """Manage system configuration."""
        action = parameters["action"]
        
        if action == "get":
            return {
                "action": "get",
                "configuration": self.admin_service.configuration,
                "timestamp": datetime.now().isoformat()
            }
        
        elif action == "update":
            config_updates = parameters.get("config_updates", {})
            create_backup = parameters.get("create_backup", True)
            validate_config = parameters.get("validate_config", True)
            
            if not config_updates:
                raise ValueError("No configuration updates provided")
            
            if validate_config:
                # Mock validation
                invalid_keys = [k for k in config_updates.keys() if not k.replace('.', '').replace('_', '').isalnum()]
                if invalid_keys:
                    raise ValueError(f"Invalid configuration keys: {invalid_keys}")
            
            result = await self.admin_service.update_configuration(config_updates, create_backup)
            
            return {
                "action": "update",
                "validation_passed": validate_config,
                **result
            }
        
        elif action == "validate":
            config_updates = parameters.get("config_updates", {})
            
            # Mock validation logic
            validation_results = []
            for key, value in config_updates.items():
                if "batch_size" in key and not isinstance(value, int):
                    validation_results.append({"key": key, "error": "Must be an integer"})
                elif "timeout" in key and value < 1:
                    validation_results.append({"key": key, "error": "Must be positive"})
                else:
                    validation_results.append({"key": key, "status": "valid"})
            
            return {
                "action": "validate",
                "validation_results": validation_results,
                "is_valid": all("error" not in r for r in validation_results)
            }
        
        elif action in ["backup", "restore"]:
            return {
                "action": action,
                "success": True,
                "message": f"Configuration {action} completed successfully",
                "timestamp": datetime.now().isoformat()
            }

class EnhancedResourceCleanupTool(EnhancedBaseMCPTool):
    """Enhanced tool for system resource cleanup and optimization."""
    
    def __init__(self, admin_service=None, validator=None, metrics_collector=None):
        super().__init__(
            name="enhanced_resource_cleanup",
            description="Clean up system resources, optimize performance, and free disk space.",
            category="admin",
            version="1.0.0",
            validator=validator or EnhancedParameterValidator(),
            metrics_collector=metrics_collector or EnhancedMetricsCollector()
        )
        
        self.admin_service = admin_service or MockAdminService()
        
        self.input_schema = {
            "type": "object",
            "properties": {
                "cleanup_type": {
                    "type": "string",
                    "description": "Type of cleanup to perform",
                    "enum": ["basic", "full", "cache_only", "temp_only", "logs_only"],
                    "default": "basic"
                },
                "restart_services": {
                    "type": "boolean",
                    "description": "Restart services after cleanup if needed",
                    "default": True
                },
                "cleanup_temp_files": {
                    "type": "boolean",
                    "description": "Clean temporary files",
                    "default": True
                },
                "cleanup_logs": {
                    "type": "boolean",
                    "description": "Clean old log files",
                    "default": False
                },
                "max_log_age_days": {
                    "type": "integer",
                    "description": "Maximum age of log files to keep",
                    "minimum": 1,
                    "maximum": 365,
                    "default": 30
                }
            }
        }
    
    async def _execute_impl(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """Clean up system resources."""
        cleanup_type = parameters.get("cleanup_type", "basic")
        restart_services = parameters.get("restart_services", True)
        cleanup_temp_files = parameters.get("cleanup_temp_files", True)
        cleanup_logs = parameters.get("cleanup_logs", False)
        max_log_age_days = parameters.get("max_log_age_days", 30)
        
        result = await self.admin_service.cleanup_resources(cleanup_type)
        
        # Add additional cleanup details
        result.update({
            "cleanup_options": {
                "restart_services": restart_services,
                "cleanup_temp_files": cleanup_temp_files,
                "cleanup_logs": cleanup_logs,
                "max_log_age_days": max_log_age_days
            },
            "performance_impact": {
                "memory_freed_percent": (result["freed_memory_bytes"] / (1024**3)) / 8.0 * 100,  # Assume 8GB system
                "disk_freed_percent": result.get("disk_space_freed_mb", 0) / 10000 * 100,  # Assume 100GB available
                "estimated_performance_improvement": "5-10%" if cleanup_type == "full" else "2-5%"
            },
            "recommendations": [
                "Consider scheduling regular cleanup operations",
                "Monitor disk usage to prevent future issues",
                "Enable automatic cache cleanup" if cleanup_type == "full" else "Run full cleanup monthly"
            ]
        })
        
        return result

# Export the enhanced tools
__all__ = [
    "EnhancedSystemStatusTool",
    "EnhancedServiceManagementTool",
    "EnhancedConfigurationTool", 
    "EnhancedResourceCleanupTool",
    "ServiceStatus",
    "MaintenanceMode",
    "SystemInfo",
    "MockAdminService"
]
