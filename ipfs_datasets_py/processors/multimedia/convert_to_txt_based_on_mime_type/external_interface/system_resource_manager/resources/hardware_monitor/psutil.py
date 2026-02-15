

import psutil
from typing import Dict, Any


class PsUtil:

    def __init__(self, resources=None, configs=None):
        self.resources = resources
        self.configs = configs

    def _get_total_cpu_cores(self) -> int:
        """
        Get the total number of physical CPU cores available on the system.
        
        Returns:
            int: The total number of CPU cores
        """
        return psutil.cpu_count(logical=True)
    
    def _get_cpu_utilization_as_percentage(self) -> float:
        """
        Get the current CPU utilization as a percentage.
        
        Returns:
            float: The CPU utilization percentage (0-100)
        """
        return psutil.cpu_percent(interval=1)

    def _get_total_memory(self) -> int:
        """
        Get the total system RAM in megabytes.
        
        Returns:
            int: Total RAM in MB
        """
        return int(psutil.virtual_memory().total / (1024 * 1024))

    def _get_free_memory(self) -> int:
        """
        Get the current free system RAM in megabytes.
        
        Returns:
            int: Free RAM in MB
        """
        return int(psutil.virtual_memory().available / (1024 * 1024))

