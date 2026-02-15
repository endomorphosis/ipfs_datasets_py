from functools import cached_property
from typing import Dict, Any, Optional, List, Tuple
import time
import psutil

from .base_resource_manager import BaseResourceManager
from .hardware_monitor import HardwareMonitor
from .resource_config import ResourceConfig
from .resource_packet import ResourcePacket
from .resource_emitter import ResourceEmitter



class SystemResourceManager:
    """
    Main system resource management class that monitors and allocates system resources.
    
    This class extends the BaseResourceManager with hardware detection, monitoring,
    and event emission capabilities. It serves as the central point for tracking
    and allocating system resources like CPU, RAM, VRAM, and disk space.
    """

    def __init__(self, resources=None, config=None):
        """
        Initialize the system resource manager.
        
        Args:
            config: ResourceConfig object containing resource limits and settings
        """
        self.hardware_monitor = HardwareMonitor()
        self.subscribers = []
        self.detect_hardware()
        self.recalculate_resources()
    
    def detect_hardware(self) -> Dict[str, Any]:
        """
        Detect and initialize hardware resources.
        
        Returns:
            Dict containing hardware detection results and capabilities
        """
        # Implementation would use the hardware monitor to detect system resources
        # and update total_resources
        pass
    
    def monitor_resource_services(self) -> Dict[str, Any]:
        """
        Monitor current resource usage and update available resources.
        
        Returns:
            Dict with current resource usage statistics
        """
        # Implementation would monitor and update resource usage
        pass

    def heartbeat(self) -> None:
        """
        Periodic function to update resource statistics and notify subscribers.
        
        This method should be called regularly to keep resource statistics current
        and emit updates to subscribers.
        """
        self.recalculate_resources()
        self.export_data_to_external_resource_manager(self.available_resources)
    
    def export_data_to_external_resource_manager(self) -> Dict[str, Any]:
        """
        Export resource statistics in a format suitable for external systems.
        
        Returns:
            Dict containing formatted resource statistics for external consumption
        """
        # Implementation would format resource data for external systems
        pass
    
    @cached_property
    def total_resources(self):
        # Get current resource stats using hardware monitor
        return ResourcePacket(
            self.hardware_monitor.get_total_cpu_cores(),
            self.hardware_monitor.get_total_memory(),
            self.hardware_monitor.get_total_vram(),
            self.hardware_monitor.get_total_disk_space()
        )

    def recalculate_resources(self) -> None:
        """
        Update resource calculations based on current system state.
        
        This method overrides the base class method to use hardware monitoring
        for accurate resource statistics.
        """
        self.available_resources = ResourcePacket(
            self.hardware_monitor.get_free_cpu_cores(),
            self.hardware_monitor.get_free_memory(),
            self.hardware_monitor.get_free_vram(),
            self.hardware_monitor.get_free_disk_space()
        )