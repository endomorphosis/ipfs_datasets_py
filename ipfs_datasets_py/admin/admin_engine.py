"""
Admin Engine — core system administration business logic.

Domain models and the mock admin service used by admin tools.
Extracted from mcp_server/tools/admin_tools/enhanced_admin_tools.py.

Reusable by:
- MCP server tools (mcp_server/tools/admin_tools/)
- CLI commands
- Direct Python imports: from ipfs_datasets_py.admin.admin_engine import MockAdminService
"""

import logging
import platform
import os
import psutil
from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta
from dataclasses import dataclass, asdict
from enum import Enum

logger = logging.getLogger(__name__)

class ServiceStatus(Enum):
    """Service status enumeration."""
    RUNNING = "running"
    STOPPED = "stopped"
    STARTING = "starting"
    STOPPING = "stopping"
    ERROR = "error"
    UNKNOWN = "unknown"

class MaintenanceMode(Enum):
    """Maintenance mode enumeration."""
    ENABLED = "enabled"
    DISABLED = "disabled"
    SCHEDULED = "scheduled"

@dataclass
class SystemInfo:
    """System information container."""
    hostname: str
    platform: str
    architecture: str
    cpu_count: int
    memory_total_gb: float
    disk_total_gb: float
    disk_free_gb: float
    python_version: str
    uptime_hours: float

class MockAdminService:
    """Mock admin service for development and testing."""
    
    def __init__(self):
        self.services = {
            "ipfs_daemon": ServiceStatus.RUNNING,
            "vector_store": ServiceStatus.RUNNING,
            "cache_service": ServiceStatus.RUNNING,
            "monitoring_service": ServiceStatus.RUNNING,
            "workflow_engine": ServiceStatus.STOPPED
        }
        self.maintenance_mode = MaintenanceMode.DISABLED
        self.configuration = {
            "embedding": {
                "batch_size": 32,
                "max_workers": 4,
                "timeout_seconds": 300
            },
            "cache": {
                "max_size_mb": 1024,
                "ttl_hours": 24,
                "cleanup_interval_minutes": 60
            },
            "security": {
                "enable_rate_limiting": True,
                "max_requests_per_minute": 100,
                "require_authentication": False
            }
        }
    
    async def get_system_status(self) -> Dict[str, Any]:
        """Get comprehensive system status."""
        # Get real system info
        system_info = SystemInfo(
            hostname=platform.node(),
            platform=platform.system(),
            architecture=platform.machine(),
            cpu_count=psutil.cpu_count(),
            memory_total_gb=psutil.virtual_memory().total / (1024**3),
            disk_total_gb=psutil.disk_usage('/').total / (1024**3),
            disk_free_gb=psutil.disk_usage('/').free / (1024**3),
            python_version=platform.python_version(),
            uptime_hours=psutil.boot_time() / 3600  # Simplified
        )
        
        return {
            "system_info": {
                "hostname": system_info.hostname,
                "platform": system_info.platform,
                "architecture": system_info.architecture,
                "cpu_count": system_info.cpu_count,
                "memory_total_gb": round(system_info.memory_total_gb, 2),
                "disk_total_gb": round(system_info.disk_total_gb, 2),
                "disk_free_gb": round(system_info.disk_free_gb, 2),
                "python_version": system_info.python_version
            },
            "services": {name: status.value for name, status in self.services.items()},
            "maintenance_mode": self.maintenance_mode.value,
            "resource_usage": {
                "cpu_percent": psutil.cpu_percent(),
                "memory_percent": psutil.virtual_memory().percent,
                "disk_percent": psutil.disk_usage('/').percent
            },
            "health_status": "healthy" if all(s == ServiceStatus.RUNNING for s in self.services.values()) else "degraded"
        }
    
    async def manage_service(self, service_name: str, action: str) -> Dict[str, Any]:
        """Manage system services."""
        if service_name not in self.services:
            raise ValueError(f"Unknown service: {service_name}")
        
        current_status = self.services[service_name]
        
        if action == "start":
            if current_status == ServiceStatus.STOPPED:
                self.services[service_name] = ServiceStatus.STARTING
                await anyio.sleep(0.1)  # Simulate startup time
                self.services[service_name] = ServiceStatus.RUNNING
            result_status = ServiceStatus.RUNNING
        elif action == "stop":
            if current_status == ServiceStatus.RUNNING:
                self.services[service_name] = ServiceStatus.STOPPING
                await anyio.sleep(0.1)  # Simulate shutdown time
                self.services[service_name] = ServiceStatus.STOPPED
            result_status = ServiceStatus.STOPPED
        elif action == "restart":
            self.services[service_name] = ServiceStatus.STOPPING
            await anyio.sleep(0.1)
            self.services[service_name] = ServiceStatus.STARTING
            await anyio.sleep(0.1)
            self.services[service_name] = ServiceStatus.RUNNING
            result_status = ServiceStatus.RUNNING
        elif action == "status":
            result_status = current_status
        else:
            raise ValueError(f"Unknown action: {action}")
        
        return {
            "service_name": service_name,
            "action": action,
            "previous_status": current_status.value,
            "current_status": result_status.value,
            "timestamp": datetime.now().isoformat()
        }
    
    async def update_configuration(self, config_updates: Dict[str, Any], create_backup: bool = True) -> Dict[str, Any]:
        """Update system configuration."""
        updated_keys = []
        backup_location = None
        
        if create_backup:
            backup_location = f"/backups/config_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        
        # Apply configuration updates
        for key_path, value in config_updates.items():
            keys = key_path.split('.')
            config_section = self.configuration
            
            # Navigate to the correct section
            for key in keys[:-1]:
                if key not in config_section:
                    config_section[key] = {}
                config_section = config_section[key]
            
            # Update the value
            config_section[keys[-1]] = value
            updated_keys.append(key_path)
        
        # Determine if restart is required
        restart_required = any('security.' in key or 'cache.max_size_mb' in key for key in updated_keys)
        
        return {
            "updated_keys": updated_keys,
            "restart_required": restart_required,
            "backup_created": create_backup,
            "backup_location": backup_location,
            "config_version": "1.2.3",
            "timestamp": datetime.now().isoformat()
        }
    
    async def cleanup_resources(self, cleanup_type: str = "basic") -> Dict[str, Any]:
        """Clean up system resources."""
        freed_memory_bytes = 0
        cleaned_temp_files = 0
        cleared_cache_entries = 0
        services_restarted = []
        
        if cleanup_type in ["basic", "full"]:
            # Mock cleanup operations
            freed_memory_bytes = 500000000  # 500MB
            cleaned_temp_files = 75
            cleared_cache_entries = 2500
        
        if cleanup_type == "full":
            freed_memory_bytes = 1000000000  # 1GB
            cleaned_temp_files = 150
            cleared_cache_entries = 5000
            services_restarted = ["cache_service"]
        
        await anyio.sleep(0.2)  # Simulate cleanup time
        
        return {
            "cleanup_type": cleanup_type,
            "freed_memory_bytes": freed_memory_bytes,
            "cleaned_temp_files": cleaned_temp_files,
            "cleared_cache_entries": cleared_cache_entries,
            "cleanup_time": 8.5 if cleanup_type == "full" else 3.2,
            "services_restarted": services_restarted,
            "disk_space_freed_mb": 256.8 if cleanup_type == "full" else 128.4
        }

